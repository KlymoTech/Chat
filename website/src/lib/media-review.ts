import "server-only";
import {randomUUID} from "node:crypto";
import {Pool} from "pg";
import type {CmsActor} from "./cms-editor";
import {getSanitizedCandidate} from "./media-storage";

const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
let reviewPool:Pool|undefined;
function reviewDatabase():Pool {
  const url=process.env.WEBSITE_MEDIA_REVIEW_DATABASE_URL;
  if(process.env.WEBSITE_MEDIA_REVIEW_ENABLED!=="true" ||
     process.env.WEBSITE_MEDIA_REVIEW_DB_ROLE_VERIFIED!=="true" || !url)
    throw new Error("Independent media review is disabled");
  if(!reviewPool)reviewPool=new Pool({connectionString:url,max:2,
    connectionTimeoutMillis:3000,idleTimeoutMillis:10000});
  return reviewPool;
}
function assertReviewer(actor:CmsActor) {
  if(!uuid.test(actor.id)||!uuid.test(actor.siteId)||
     !actor.permissions.includes("cms:media:review"))
    throw new Error("Independent review permission required");
}
export type MediaReviewAction="approve"|"reject";
export type MediaReviewEntry=Readonly<{
  id:string;originalFilename:string;state:string;blobStatus:string;
  createdByActorId:string;altDefault:string;rightsStatement:string;
  scanEngine:string|null;scannedAt:string|null;sanitizedSha256:string|null;
}>;
export async function listMediaForReview(actor:CmsActor):Promise<MediaReviewEntry[]> {
  assertReviewer(actor);
  const r=await reviewDatabase().query<MediaReviewEntry>(
    `SELECT id::text AS id,original_filename AS "originalFilename",
            state,blob_status AS "blobStatus",
            created_by_actor_id::text AS "createdByActorId",
            alt_default AS "altDefault",rights_statement AS "rightsStatement",
            scan_engine AS "scanEngine",scanned_at::text AS "scannedAt",
            sanitized_sha256 AS "sanitizedSha256"
       FROM website_cms.media_assets
      WHERE site_id=$1 AND state='quarantined'
      ORDER BY created_at ASC LIMIT 100`,
    [actor.siteId]);
  return r.rows;
}
/** Independent decision never exposes public object storage nor deletes source. */
export async function reviewPrivateMedia(
  actor:CmsActor,assetId:string,action:MediaReviewAction,reason:string,
  reviewedSha256?:string,
):Promise<{assetId:string;state:"approved"|"rejected";publicAccess:false}> {
  assertReviewer(actor);
  if(!uuid.test(assetId)||!["approve","reject"].includes(action)||
     typeof reason!=="string"||reason.trim().length<10||reason.trim().length>500)
    throw new Error("Invalid media review request");
  const db=reviewDatabase();
  const client=await db.connect();
  try{
    await client.query("BEGIN");
    const found=await client.query<{
      created_by_actor_id:string;state:string;blob_status:string;
      scanned_at:string|null;inspected_at:string|null;scan_engine:string|null;
      sanitized_key:string|null;sanitized_sha256:string|null;
      sanitized_byte_size:string|null;scanner_receipt_sha256:string|null;
      detected_mime:string|null;verified_sha256:string|null;
      verified_byte_size:string|null;claimed_mime:string;
      claimed_sha256:string;claimed_byte_size:string;
      alt_default:string;rights_statement:string;
    }>(
      `SELECT created_by_actor_id::text,state,blob_status,scanned_at::text,
              inspected_at::text,scan_engine,sanitized_key,sanitized_sha256,
              sanitized_byte_size::text,scanner_receipt_sha256,
              detected_mime,verified_sha256,verified_byte_size::text,
              claimed_mime,claimed_sha256,claimed_byte_size::text,
              alt_default,rights_statement
         FROM website_cms.media_assets
        WHERE site_id=$1 AND id=$2 FOR UPDATE`,
      [actor.siteId,assetId]);
    if(found.rowCount!==1)throw new Error("Unknown site media");
    const media=found.rows[0];
    if(media.state!=="quarantined")throw new Error("Media already reviewed");
    if(media.created_by_actor_id.toLowerCase()===actor.id.toLowerCase())
      throw new Error("Creator cannot independently approve or reject own media");
    if(action==="approve" && (!reviewedSha256 ||
       !/^[0-9a-f]{64}$/.test(reviewedSha256) ||
       reviewedSha256!==media.sanitized_sha256))
      throw new Error("Reviewed preview checksum no longer matches candidate");
    if(action==="approve" && (
       media.blob_status!=="uploaded" ||
       !media.scanned_at || !media.inspected_at || !media.scan_engine ||
       !media.sanitized_key || !media.sanitized_sha256 ||
       !media.sanitized_byte_size || !media.scanner_receipt_sha256 ||
       !media.alt_default.trim() || !media.rights_statement.trim() ||
       media.detected_mime!==media.claimed_mime ||
       media.verified_sha256!==media.claimed_sha256 ||
       media.verified_byte_size!==media.claimed_byte_size
    ))throw new Error("Media has not passed scan, provenance or rights gates");
    const changed=await client.query(
      `UPDATE website_cms.media_assets
          SET state=$3,reviewed_by_actor_id=$4,reviewed_at=now()
        WHERE site_id=$1 AND id=$2 AND state='quarantined'`,
      [actor.siteId,assetId,action==="approve"?"approved":"rejected",actor.id]);
    if(changed.rowCount!==1)throw new Error("Concurrent review conflict");
    await client.query(
      `INSERT INTO website_cms.audit_events
         (id,site_id,actor_id,action,target_id,metadata)
       VALUES($1,$2,$3,$4,$5,
         jsonb_build_object('reason',$6::text,'reviewedSeparately',true))`,
      [randomUUID(),actor.siteId,actor.id,
       action==="approve"?"cms.media_review_approved":"cms.media_review_rejected",
       assetId,reason.trim()]);
    await client.query("COMMIT");
    return {assetId,state:action==="approve"?"approved":"rejected",publicAccess:false};
  }catch(error){
    try{await client.query("ROLLBACK");}catch{}
    throw error;
  }finally{client.release();}
}

/** Authenticated reviewer preview of independently sanitized and scanned bytes. */
export async function loadPrivateReviewImage(
  actor:CmsActor,assetId:string,
):Promise<Uint8Array> {
  assertReviewer(actor);
  if(!uuid.test(assetId))throw new Error("Invalid media ID");
  const r=await reviewDatabase().query<{
    sanitized_key:string;sanitized_sha256:string;sanitized_byte_size:string;
  }>(
    `SELECT sanitized_key,sanitized_sha256,sanitized_byte_size::text
       FROM website_cms.media_assets
      WHERE site_id=$1 AND id=$2 AND state='quarantined'
        AND scanned_at IS NOT NULL AND inspected_at IS NOT NULL
        AND sanitized_key IS NOT NULL AND sanitized_sha256 IS NOT NULL`,
    [actor.siteId,assetId]);
  if(r.rowCount!==1)throw new Error("No reviewed candidate");
  const item=r.rows[0];
  return getSanitizedCandidate(item.sanitized_key,item.sanitized_sha256,
    Number(item.sanitized_byte_size));
}
