import "server-only";
import {randomUUID} from "node:crypto";
import {Pool} from "pg";
import {getQuarantineObject,putSanitizedCandidate} from "./media-storage";
import {inspectQuarantinedImage} from "./media-inspection";
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
let pool:Pool|undefined;
function scannerDatabase():Pool {
  const url=process.env.WEBSITE_MEDIA_SCANNER_DATABASE_URL;
  if(process.env.WEBSITE_MEDIA_SCAN_ENABLED!=="true" ||
     process.env.WEBSITE_MEDIA_SCANNER_DB_ROLE_VERIFIED!=="true" ||
     !url)throw new Error("Media scanner not activated");
  if(!pool)pool=new Pool({connectionString:url,max:2,
    connectionTimeoutMillis:3000,idleTimeoutMillis:10000,
    query_timeout:40000});
  return pool;
}
/**
 * Independently inspect uploaded, private media. Scan both original and
 * re-encoded image. The record is NEVER marked approved or published here.
 */
export async function inspectPrivateMedia(
  siteId:string,assetId:string,
):Promise<{assetId:string;status:"inspected-quarantined"}> {
  const scannerActor=process.env.WEBSITE_MEDIA_SCANNER_ACTOR_ID;
  if(!uuid.test(siteId)||!uuid.test(assetId)||!scannerActor||
     !uuid.test(scannerActor))throw new Error("Invalid scanner request");
  const client=await scannerDatabase().connect();
  try{
    await client.query("BEGIN");
    await client.query("SET LOCAL lock_timeout = '3s'");
    const query=await client.query<{
      quarantine_key:string;blob_status:string;state:string;
      claimed_sha256:string;claimed_byte_size:string;claimed_mime:string;
      scanned_at:string|null;
    }>(
      `SELECT quarantine_key,blob_status,state,claimed_sha256,
              claimed_byte_size::text,claimed_mime,scanned_at::text
         FROM website_cms.media_assets
        WHERE site_id=$1 AND id=$2 FOR UPDATE`,[siteId,assetId]);
    if(query.rowCount!==1)throw new Error("Unknown private media");
    const media=query.rows[0];
    if(media.state!=="quarantined" || media.blob_status!=="uploaded" || media.scanned_at)
      throw new Error("Media is not awaiting inspection");
    const bytes=await getQuarantineObject(media.quarantine_key);
    const inspected=await inspectQuarantinedImage(bytes);
    if(inspected.originalSha256!==media.claimed_sha256 ||
       inspected.originalSize!==Number(media.claimed_byte_size) ||
       inspected.originalMime!==media.claimed_mime)
      throw new Error("Inspected source differs from reserved manifest");

    const sanitizedKey=`processed/${siteId}/${assetId}/candidate.webp`;
    await putSanitizedCandidate(sanitizedKey,inspected.sanitized,inspected.sanitizedSha256);
    const changed=await client.query(
      `UPDATE website_cms.media_assets
          SET detected_mime=$3,verified_sha256=$4,verified_byte_size=$5,
              verified_width=$6,verified_height=$7,scanner_receipt_sha256=$8,
              scanned_at=now(),sanitized_key=$9,sanitized_sha256=$10,
              sanitized_byte_size=$11,scan_engine=$12,inspected_at=now()
        WHERE site_id=$1 AND id=$2 AND state='quarantined'
          AND blob_status='uploaded' AND scanned_at IS NULL`,
      [siteId,assetId,inspected.originalMime,inspected.originalSha256,
       inspected.originalSize,inspected.width,inspected.height,
       inspected.scannerReceiptSha256,sanitizedKey,inspected.sanitizedSha256,
       inspected.sanitized.length,inspected.scanEngine]);
    if(changed.rowCount!==1)throw new Error("Concurrent inspection conflict");
    await client.query(
      `INSERT INTO website_cms.audit_events
         (id,site_id,actor_id,action,target_id,metadata)
       VALUES($1,$2,$3,'cms.media_inspected_quarantined',$4,
         jsonb_build_object('scanEngine',$5::text,'receipt',$6::text,
                            'sanitizedSha256',$7::text))`,
      [randomUUID(),siteId,scannerActor,assetId,
       inspected.scanEngine,inspected.scannerReceiptSha256,inspected.sanitizedSha256]);
    await client.query("COMMIT");
    return {assetId,status:"inspected-quarantined"};
  }catch(error){
    try{await client.query("ROLLBACK");}catch{}
    // Storage/SQL is not an atomic transaction; leave any private candidate
    // for operator-controlled reconciliation rather than auto-deleting evidence.
    throw error;
  }finally{client.release();}
}
