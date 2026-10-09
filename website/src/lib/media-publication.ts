import "server-only";
import {randomUUID} from "node:crypto";
import {Pool} from "pg";
import type {CmsActor} from "./cms-editor";

const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export type MediaPublicationAction="publish"|"withdraw";
export type ApprovedMediaRow=Readonly<{
  id:string; originalFilename:string;altDefault:string;
  rightsStatement:string;publishedAt:string|null;withdrawnAt:string|null;
  livePageCount:number;
}>;
let database:Pool|undefined;
function publicationDatabase():Pool {
  const url=process.env.WEBSITE_MEDIA_PUBLICATION_DATABASE_URL;
  if(process.env.WEBSITE_MEDIA_PUBLICATION_ENABLED!=="true"||
     process.env.WEBSITE_MEDIA_PUBLISH_DB_ROLE_VERIFIED!=="true"||!url)
    throw new Error("Public media publication disabled");
  if(!database)database=new Pool({connectionString:url,max:2,
    connectionTimeoutMillis:3000,idleTimeoutMillis:10000});
  return database;
}
function authorize(actor:CmsActor):void {
  if(!uuid.test(actor.id)||!uuid.test(actor.siteId)||
     !actor.permissions.includes("cms:media:publish"))
    throw new Error("Media publication permission required");
}
/** Private owner list only; neither storage keys nor hashes exposed. */
export async function listApprovedMedia(actor:CmsActor):Promise<ApprovedMediaRow[]> {
  authorize(actor);
  const result=await publicationDatabase().query<ApprovedMediaRow>(
    `SELECT m.id::text,m.original_filename AS "originalFilename",
            m.alt_default AS "altDefault",m.rights_statement AS "rightsStatement",
            m.published_at::text AS "publishedAt",
            m.withdrawn_at::text AS "withdrawnAt",
            (SELECT COUNT(*)::integer FROM website_cms.media_usages u
               JOIN website_cms.pages p ON p.site_id=u.site_id AND p.id=u.page_id
              WHERE u.site_id=m.site_id AND u.asset_id=m.id
                AND p.current_published_revision_id=u.revision_id
                AND p.trashed_at IS NULL) AS "livePageCount"
       FROM website_cms.media_assets m
      WHERE m.site_id=$1 AND m.state='approved'
      ORDER BY m.reviewed_at DESC LIMIT 100`,[actor.siteId]);
  return result.rows;
}
/**
 * Publication is a distinct, attributable action after scan and human review.
 * Withdraw immediately excludes it from the public SQL view; no CDN caching
 * is permitted by the read route. Source files remain permanently private.
 */
export async function decideMediaPublication(
  actor:CmsActor,assetId:string,action:MediaPublicationAction,reason:string,
  impactAcknowledged=false,
):Promise<{assetId:string;published:boolean;livePageCount:number}> {
  authorize(actor);
  if(!uuid.test(assetId)||(action!=="publish"&&action!=="withdraw")||
     typeof reason!=="string"||reason.trim().length<10||reason.trim().length>500)
    throw new Error("Invalid public media decision");
  const client=await publicationDatabase().connect();
  try {
    await client.query("BEGIN");
    const result=await client.query<{
      state:string;created_by_actor_id:string;reviewed_by_actor_id:string|null;
      scanned_at:string|null;inspected_at:string|null;sanitized_key:string|null;
      sanitized_sha256:string|null;sanitized_byte_size:string|null;
      published_at:string|null;withdrawn_at:string|null;
      alt_default:string;rights_statement:string;
    }>(
      `SELECT state,created_by_actor_id::text,reviewed_by_actor_id::text,
              scanned_at::text,inspected_at::text,sanitized_key,
              sanitized_sha256,sanitized_byte_size::text,
              published_at::text,withdrawn_at::text,alt_default,rights_statement
         FROM website_cms.media_assets WHERE site_id=$1 AND id=$2 FOR UPDATE`,
      [actor.siteId,assetId]);
    if(result.rowCount!==1)throw new Error("Media record unavailable");
    const media=result.rows[0];
    if(media.state!=="approved"||!media.reviewed_by_actor_id||
       !media.scanned_at||!media.inspected_at||!media.sanitized_key||
       !media.sanitized_sha256||!media.sanitized_byte_size||
       !media.alt_default.trim()||!media.rights_statement.trim()||
       media.reviewed_by_actor_id.toLowerCase()===media.created_by_actor_id.toLowerCase())
      throw new Error("Media approval/scan requirements not met");
    const liveUsage=await client.query<{total:number}>(
      `SELECT COUNT(*)::integer AS total
         FROM website_cms.media_usages u
         JOIN website_cms.pages p ON p.site_id=u.site_id AND p.id=u.page_id
        WHERE u.site_id=$1 AND u.asset_id=$2
          AND p.current_published_revision_id=u.revision_id
          AND p.trashed_at IS NULL`,
      [actor.siteId,assetId]);
    const livePageCount=liveUsage.rows[0]?.total??0;
    if(action==="withdraw" && livePageCount>0 && !impactAcknowledged)
      throw new Error("Acknowledge active page references before withdrawal");
    if(action==="publish"){
      if(media.published_at&&!media.withdrawn_at)
        throw new Error("Media is already public");
      if(media.created_by_actor_id.toLowerCase()===actor.id.toLowerCase())
        throw new Error("Uploader cannot publish own media");
      await client.query(
        `UPDATE website_cms.media_assets
            SET published_at=now(),published_by_actor_id=$3,
                withdrawn_at=NULL,withdrawn_by_actor_id=NULL
          WHERE site_id=$1 AND id=$2 AND state='approved'`,
        [actor.siteId,assetId,actor.id]);
    }else{
      if(!media.published_at||media.withdrawn_at)
        throw new Error("Media is not currently public");
      await client.query(
        `UPDATE website_cms.media_assets
            SET withdrawn_at=now(),withdrawn_by_actor_id=$3
          WHERE site_id=$1 AND id=$2 AND state='approved'`,
        [actor.siteId,assetId,actor.id]);
    }
    await client.query(
      `INSERT INTO website_cms.audit_events
         (id,site_id,actor_id,action,target_id,metadata)
       VALUES($1,$2,$3,$4,$5,
         jsonb_build_object('reason',$6::text,'livePageCount',$7::integer,
                            'impactAcknowledged',$8::boolean))`,
      [randomUUID(),actor.siteId,actor.id,
       action==="publish"?"cms.media_published":"cms.media_withdrawn",
       assetId,reason.trim(),livePageCount,impactAcknowledged]);
    await client.query("COMMIT");
    return {assetId,published:action==="publish",livePageCount};
  }catch(error){
    try{await client.query("ROLLBACK");}catch{}
    throw error;
  }finally{client.release();}
}
