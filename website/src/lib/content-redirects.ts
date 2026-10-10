import "server-only";
import {randomUUID} from "node:crypto";
import {Pool} from "pg";
import type {CmsActor} from "./cms-editor";
import {parseRedirectDraft,isRedirectLookupSource,REDIRECT_DESTINATION,
 type RedirectDraft} from "./redirect-contract";
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
let privateDb:Pool|undefined,publicDb:Pool|undefined;
function ownerDatabase():Pool {
  if(process.env.WEBSITE_REDIRECT_EDITOR_ENABLED!=="true"||
     process.env.WEBSITE_REDIRECT_EDITOR_GRANTS_VERIFIED!=="true"||
     !process.env.WEBSITE_REDIRECT_EDITOR_DATABASE_URL)
    throw new Error("Redirect editor unavailable");
  if(!privateDb)privateDb=new Pool({
    connectionString:process.env.WEBSITE_REDIRECT_EDITOR_DATABASE_URL,
    max:3,connectionTimeoutMillis:2500,query_timeout:5000,
  });
  return privateDb;
}
function assertRedirectOwner(actor:CmsActor){
  if(!uuid.test(actor.id)||!uuid.test(actor.siteId)||
     !actor.permissions.includes("cms:redirect"))throw Error("Redirect permission denied");
}
export type OwnerRedirect={
  id:string;sourcePath:string;targetPath:string;
  reasonCode:string;status:"draft"|"approved"|"suspended";
  requestedBy:string;reviewedBy:string|null;
};
export async function listOwnerRedirects(actor:CmsActor):Promise<OwnerRedirect[]>{
  assertRedirectOwner(actor);
  const data=await ownerDatabase().query<OwnerRedirect>(
    `SELECT id::text,source_path AS "sourcePath",target_path AS "targetPath",
        reason_code AS "reasonCode",status,
        requested_by::text AS "requestedBy",reviewed_by::text AS "reviewedBy"
       FROM website_cms.content_redirects
      WHERE site_id=$1 ORDER BY created_at DESC LIMIT 100`,[actor.siteId]);
  return data.rows;
}
export async function createRedirectDraft(actor:CmsActor,input:unknown):
Promise<{id:string;status:"draft"}>{
  assertRedirectOwner(actor);
  const draft=parseRedirectDraft(input);
  if(!draft)throw Error("Invalid content redirect");
  const client=await ownerDatabase().connect();
  const id=randomUUID();
  try{
    await client.query("BEGIN");
    const created=await client.query(
      `INSERT INTO website_cms.content_redirects
         (id,site_id,source_path,target_path,reason_code,requested_by)
       VALUES($1,$2,$3,$4,$5,$6) RETURNING id`,
      [id,actor.siteId,draft.sourcePath,draft.targetPath,draft.reasonCode,actor.id]);
    if(created.rowCount!==1)throw Error("Could not create redirect");
    await client.query(
      `INSERT INTO website_cms.audit_events(id,site_id,actor_id,action,target_id)
       VALUES($1,$2,$3,'cms.redirect_drafted',$4)`,
      [randomUUID(),actor.siteId,actor.id,id]);
    await client.query("COMMIT");
    return {id,status:"draft"};
  }catch(error){
    try{await client.query("ROLLBACK");}catch{}
    throw error;
  }finally{client.release();}
}
/** Approve only unoccupied old paths and live same-site destinations. */
export async function reviewRedirect(actor:CmsActor,id:string,
  decision:"approve"|"suspend"):Promise<{id:string;status:"approved"|"suspended"}>{
  assertRedirectOwner(actor);
  if(!uuid.test(id))throw Error("Invalid redirect identity");
  const client=await ownerDatabase().connect();
  try{
    await client.query("BEGIN ISOLATION LEVEL SERIALIZABLE");
    // Serializes approvals for a site to prevent concurrent redirect chains.
    const site=await client.query(
      `SELECT id FROM website_cms.sites WHERE id=$1 FOR UPDATE`,[actor.siteId]);
    if(site.rowCount!==1)throw Error("Site not provisioned");
    const row=await client.query<{
      source_path:string;target_path:string;status:string;requested_by:string;
    }>(
      `SELECT source_path,target_path,status,requested_by::text
         FROM website_cms.content_redirects
        WHERE id=$1 AND site_id=$2 FOR UPDATE`,[id,actor.siteId]);
    if(row.rowCount!==1)throw Error("Redirect not found");
    const record=row.rows[0];
    if(decision==="approve"){
      if(!["draft","suspended"].includes(record.status))throw Error("Already approved");
      if(record.requested_by===actor.id)throw Error("Independent reviewer required");
      if(!isRedirectLookupSource(record.source_path)||
         !REDIRECT_DESTINATION.test(record.target_path))throw Error("Unsafe redirect paths");
      const existing=await client.query(
        `SELECT 1 FROM website_cms.pages
          WHERE site_id=$1 AND path=$2 LIMIT 1`,[actor.siteId,record.source_path]);
      if(existing.rowCount)throw Error("Old route is still owned by a CMS page");
      const chain=await client.query(
        `SELECT 1 FROM website_cms.content_redirects
          WHERE site_id=$1 AND status='approved'
            AND (source_path=$2 OR target_path=$3) LIMIT 1`,
        [actor.siteId,record.target_path,record.source_path]);
      if(chain.rowCount)throw Error("Redirect chains and loops are forbidden");
      if(record.target_path.startsWith("/content/")){
        const live=await client.query(
          `SELECT 1 FROM website_cms.pages p
            JOIN website_cms.page_revisions r
              ON r.id=p.current_published_revision_id AND r.page_id=p.id
           WHERE p.site_id=$1 AND p.path=$2 AND r.state='published'
           LIMIT 1`,[actor.siteId,record.target_path]);
        if(!live.rowCount)throw Error("Redirect destination is not published");
      }
      await client.query(
        `UPDATE website_cms.content_redirects
            SET status='approved',reviewed_by=$3,reviewed_at=now(),
                suspended_at=NULL
          WHERE id=$1 AND site_id=$2`,[id,actor.siteId,actor.id]);
    }else{
      if(record.status!=="approved")throw Error("Redirect is not approved");
      await client.query(
        `UPDATE website_cms.content_redirects
            SET status='suspended',suspended_at=now()
          WHERE id=$1 AND site_id=$2`,[id,actor.siteId]);
    }
    await client.query(
      `INSERT INTO website_cms.audit_events
        (id,site_id,actor_id,action,target_id)
       VALUES($1,$2,$3,$4,$5)`,[randomUUID(),actor.siteId,actor.id,
        decision==="approve"?"cms.redirect_approved":"cms.redirect_suspended",id]);
    await client.query("COMMIT");
    return {id,status:decision==="approve"?"approved":"suspended"};
  }catch(error){
    try{await client.query("ROLLBACK");}catch{}
    throw error;
  }finally{client.release();}
}
/** Public traffic uses only a DBA-authorized security-barrier view. */
export async function lookupPublicContentRedirect(path:string):Promise<string|null>{
  if(!isRedirectLookupSource(path)||
     process.env.WEBSITE_REDIRECT_PUBLIC_ENABLED!=="true"||
     process.env.WEBSITE_REDIRECT_PUBLIC_GRANTS_VERIFIED!=="true"||
     !process.env.WEBSITE_REDIRECT_PUBLIC_DATABASE_URL||
     !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(process.env.WEBSITE_CMS_SITE_SLUG??""))
    return null;
  try{
    if(!publicDb)publicDb=new Pool({
      connectionString:process.env.WEBSITE_REDIRECT_PUBLIC_DATABASE_URL,
      max:3,connectionTimeoutMillis:2500,query_timeout:3500,
    });
    const r=await publicDb.query<{target_path:string}>(
      `SELECT target_path FROM website_cms.public_approved_content_redirects
        WHERE site_slug=$1 AND source_path=$2 LIMIT 1`,
      [process.env.WEBSITE_CMS_SITE_SLUG,path]);
    const target=r.rows[0]?.target_path;
    return typeof target==="string"&&REDIRECT_DESTINATION.test(target)&&
      target!==path?target:null;
  }catch{return null;}
}
