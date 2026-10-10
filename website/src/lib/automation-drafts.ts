import "server-only";
import {randomUUID} from "node:crypto";
import {Pool} from "pg";
import type {CmsActor} from "./cms-editor";
import {validateAutomation,type AutomationDefinition} from "./automation-contract";
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
let pool:Pool|undefined;
function db():Pool {
  if(process.env.WEBSITE_AUTOMATION_DRAFTS_ENABLED!=="true" ||
     process.env.WEBSITE_AUTOMATION_DB_ROLE_VERIFIED!=="true" ||
     !process.env.WEBSITE_AUTOMATION_DATABASE_URL)
    throw new Error("Automation draft storage not enabled");
  if(!pool)pool=new Pool({connectionString:process.env.WEBSITE_AUTOMATION_DATABASE_URL,
    max:3,connectionTimeoutMillis:2500,query_timeout:5000});
  return pool;
}
function authorize(actor:CmsActor){
  if(!uuid.test(actor.id)||!uuid.test(actor.siteId)||
     !actor.permissions.includes("cms:automation"))
    throw new Error("Automation owner permission required");
}
export type AutomationDraftSummary={
 id:string;title:string;version:number;updatedAt:string;
};
export async function listAutomationDrafts(actor:CmsActor):Promise<AutomationDraftSummary[]> {
  authorize(actor);
  const r=await db().query<AutomationDraftSummary>(
    `SELECT d.id::text,d.title,v.version,v.created_at::text AS "updatedAt"
      FROM website_cms.automation_definitions d
      JOIN LATERAL (
        SELECT version,created_at FROM website_cms.automation_versions
        WHERE site_id=d.site_id AND definition_id=d.id
        ORDER BY version DESC LIMIT 1
      ) v ON true
      WHERE d.site_id=$1 ORDER BY v.created_at DESC LIMIT 50`,[actor.siteId]);
  return r.rows;
}
export async function createAutomationDraft(
  actor:CmsActor,unknown:unknown,
):Promise<{id:string;version:1;status:"draft"}> {
  authorize(actor);
  const definition=validateAutomation(unknown);
  if(!definition)throw new Error("Invalid automation graph");
  const client=await db().connect();
  const id=randomUUID(),versionId=randomUUID();
  try{
    await client.query("BEGIN");
    const row=await client.query(
      `INSERT INTO website_cms.automation_definitions(id,site_id,owner_actor_id,title)
       SELECT $1,s.id,$2,$3 FROM website_cms.sites s WHERE s.id=$4 RETURNING id`,
      [id,actor.id,definition.title,actor.siteId]);
    if(row.rowCount!==1)throw new Error("Site not provisioned");
    await client.query(
      `INSERT INTO website_cms.automation_versions(
         id,site_id,definition_id,version,definition,created_by_actor_id)
       VALUES($1,$2,$3,1,$4::jsonb,$5)`,
      [versionId,actor.siteId,id,JSON.stringify(definition),actor.id]);
    await client.query(
      `INSERT INTO website_cms.audit_events(id,site_id,actor_id,action,target_id)
       VALUES($1,$2,$3,'cms.automation_draft_created',$4)`,
      [randomUUID(),actor.siteId,actor.id,id]);
    await client.query("COMMIT");
    return {id,version:1,status:"draft"};
  }catch(error){
    try{await client.query("ROLLBACK");}catch{}
    throw error;
  }finally{client.release();}
}
export async function saveAutomationRevision(
  actor:CmsActor,id:string,expectedVersion:number,unknown:unknown,
):Promise<{id:string;version:number;status:"draft"}>{
  authorize(actor);
  if(!uuid.test(id)||!Number.isSafeInteger(expectedVersion)||expectedVersion<1)
    throw new Error("Invalid expected draft version");
  const definition=validateAutomation(unknown);
  if(!definition)throw new Error("Invalid automation graph");
  const client=await db().connect();
  try{
    await client.query("BEGIN");
    const owner=await client.query(
      `SELECT id FROM website_cms.automation_definitions
        WHERE id=$1 AND site_id=$2 FOR UPDATE`,[id,actor.siteId]);
    if(owner.rowCount!==1)throw new Error("Automation draft not found");
    const latest=await client.query<{version:number}>(
      `SELECT version FROM website_cms.automation_versions
        WHERE definition_id=$1 AND site_id=$2
        ORDER BY version DESC LIMIT 1`,[id,actor.siteId]);
    if(latest.rowCount!==1||latest.rows[0].version!==expectedVersion)
      throw new Error("Draft version conflict; reload before saving");
    const next=expectedVersion+1;
    await client.query(
      `INSERT INTO website_cms.automation_versions
       (id,site_id,definition_id,version,definition,created_by_actor_id)
       VALUES($1,$2,$3,$4,$5::jsonb,$6)`,
      [randomUUID(),actor.siteId,id,next,JSON.stringify(definition),actor.id]);
    await client.query(
      `INSERT INTO website_cms.audit_events(id,site_id,actor_id,action,target_id,
         metadata) VALUES($1,$2,$3,'cms.automation_draft_updated',$4,
         jsonb_build_object('version',$5::integer))`,
      [randomUUID(),actor.siteId,actor.id,id,next]);
    await client.query("COMMIT");
    return {id,version:next,status:"draft"};
  }catch(error){
    try{await client.query("ROLLBACK");}catch{}
    throw error;
  }finally{client.release();}
}
export async function getAutomationDefinition(actor:CmsActor,id:string):
Promise<{id:string;version:number;definition:AutomationDefinition}|null> {
  authorize(actor);
  if(!uuid.test(id))return null;
  const r=await db().query<{id:string;version:number;definition:AutomationDefinition}>(
    `SELECT d.id::text,v.version,v.definition
       FROM website_cms.automation_definitions d
       JOIN website_cms.automation_versions v
         ON v.site_id=d.site_id AND v.definition_id=d.id
      WHERE d.site_id=$1 AND d.id=$2
      ORDER BY v.version DESC LIMIT 1`,[actor.siteId,id]);
  return r.rows[0]??null;
}
