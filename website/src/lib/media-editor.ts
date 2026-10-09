import "server-only";
import {randomUUID} from "node:crypto";
import {Pool} from "pg";
import type {CmsActor} from "./cms-editor";
import {parseMediaManifest, type MediaManifest} from "./media-contract";
import {verifyQuarantinedBytes} from "./media-bytes";
import {putQuarantineObject} from "./media-storage";

const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
let db:Pool|undefined;
function mediaDb():Pool {
  if (process.env.WEBSITE_MEDIA_MANIFEST_ENABLED!=="true" ||
      !process.env.WEBSITE_CMS_EDITOR_DATABASE_URL) throw new Error("Media intake not enabled");
  if(!db)db=new Pool({connectionString:process.env.WEBSITE_CMS_EDITOR_DATABASE_URL,
    max:3,connectionTimeoutMillis:3000,idleTimeoutMillis:10000});
  return db;
}
function authorize(actor:CmsActor):void {
  if(!uuid.test(actor.id)||!uuid.test(actor.siteId)||
     !actor.permissions.includes("cms:media"))throw new Error("Media access denied");
}
export type OwnerMediaRecord = {
  id:string;
  originalFilename:string;
  claimedMime:string;
  claimedByteSize:string;
  altDefault:string;
  rightsStatement:string;
  provenance:MediaManifest["provenance"];
  state:string;
  blobStatus:string;
  createdAt:string;
};

/** Site-scoped private manifest listing. Never includes storage keys or raw file bytes. */
export async function listOwnerMedia(actor:CmsActor):Promise<OwnerMediaRecord[]> {
  authorize(actor);
  const r=await mediaDb().query<OwnerMediaRecord>(
    `SELECT id::text AS id,original_filename AS "originalFilename",
            claimed_mime AS "claimedMime",
            claimed_byte_size::text AS "claimedByteSize",
            alt_default AS "altDefault",rights_statement AS "rightsStatement",
            provenance,state,blob_status AS "blobStatus",created_at::text AS "createdAt"
       FROM website_cms.media_assets
      WHERE site_id=$1 ORDER BY created_at DESC LIMIT 100`,
    [actor.siteId],
  );
  return r.rows;
}

/**
 * Reserve a QUARANTINE manifest and audit record in one transaction.
 * This intentionally does not upload bytes or attest scanning/review.
 * There is NO owner approval, publish or public-download route.
 */
export async function reserveMediaManifest(
  actor:CmsActor,value:unknown,
):Promise<{assetId:string;state:"quarantined";blobStatus:"not_uploaded"}> {
  authorize(actor);
  const input=parseMediaManifest(value);
  if(!input)throw new Error("Invalid or unsafe media manifest");
  const assetId=randomUUID();
  const quarantineKey=`quarantine/${actor.siteId}/${assetId}/original`;
  const client=await mediaDb().connect();
  try{
    await client.query("BEGIN");
    const inserted=await client.query(
      `INSERT INTO website_cms.media_assets(
        id,site_id,created_by_actor_id,original_filename,claimed_mime,
        claimed_sha256,claimed_byte_size,quarantine_key,alt_default,
        rights_statement,provenance
      ) SELECT $1,s.id,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb
        FROM website_cms.sites s WHERE s.id=$11 RETURNING id`,
      [assetId,actor.id,input.originalFilename,input.claimedMime,
       input.claimedSha256,input.claimedByteSize,quarantineKey,
       input.altDefault,input.rightsStatement,JSON.stringify(input.provenance),actor.siteId],
    );
    if(inserted.rowCount!==1)throw new Error("Site does not exist");
    await client.query(
      `INSERT INTO website_cms.audit_events(
         id,site_id,actor_id,action,target_id,metadata
       ) VALUES($1,$2,$3,'cms.media_manifest_reserved',$4,
         jsonb_build_object('mime',$5::text,'size',$6::bigint))`,
      [randomUUID(),actor.siteId,actor.id,assetId,input.claimedMime,input.claimedByteSize],
    );
    await client.query("COMMIT");
    return {assetId,state:"quarantined",blobStatus:"not_uploaded"};
  }catch(error){
    try{await client.query("ROLLBACK");}catch{}
    throw error;
  }finally{client.release();}
}

export class MediaUploadRejected extends Error {}
export class MediaUploadConflict extends Error {}

/**
 * Authorize, verify and store raw bytes in the PRIVATE quarantine bucket.
 * Hold the media row lock until storage acknowledgement and audit commit:
 * two competing requests cannot silently replace an accepted source blob.
 * This step is NOT malware scanning or publication approval.
 */
export async function uploadQuarantinedMedia(
  actor:CmsActor,assetId:string,bytes:Uint8Array,
):Promise<{assetId:string;state:"quarantined";blobStatus:"uploaded"}> {
  authorize(actor);
  if(process.env.WEBSITE_MEDIA_UPLOAD_ENABLED!=="true")
    throw new Error("Quarantine uploads are disabled");
  if(!uuid.test(assetId)||bytes.byteLength>10*1024*1024||bytes.byteLength<12)
    throw new MediaUploadRejected("Invalid asset identifier or file size");
  const client=await mediaDb().connect();
  try{
    await client.query("BEGIN");
    await client.query("SET LOCAL lock_timeout = '3s'");
    const found=await client.query<{
      state:string;blob_status:string;quarantine_key:string;
      claimed_mime:string;claimed_sha256:string;claimed_byte_size:string;
    }>(
      `SELECT state,blob_status,quarantine_key,claimed_mime,
              claimed_sha256,claimed_byte_size::text
         FROM website_cms.media_assets
        WHERE id=$1 AND site_id=$2 FOR UPDATE`,
      [assetId,actor.siteId],
    );
    if(found.rowCount!==1)throw new MediaUploadRejected("Unknown media manifest");
    const manifest=found.rows[0];
    if(manifest.state!=="quarantined")
      throw new MediaUploadConflict("Only quarantined records may receive bytes");
    const inspected=verifyQuarantinedBytes(bytes,{
      mime:manifest.claimed_mime,
      sha256:manifest.claimed_sha256,
      byteSize:Number(manifest.claimed_byte_size),
    });
    if(!inspected)throw new MediaUploadRejected("File bytes do not match the manifest");
    if(manifest.blob_status==="uploaded"){
      await client.query("COMMIT");
      return {assetId,state:"quarantined",blobStatus:"uploaded"};
    }
    if(manifest.blob_status!=="not_uploaded")
      throw new MediaUploadConflict("Unexpected quarantine storage state");
    await putQuarantineObject(manifest.quarantine_key,bytes,inspected);
    await client.query(
      `UPDATE website_cms.media_assets
          SET blob_status='uploaded'
        WHERE id=$1 AND site_id=$2 AND state='quarantined'
          AND blob_status='not_uploaded'`,
      [assetId,actor.siteId],
    );
    await client.query(
      `INSERT INTO website_cms.audit_events(id,site_id,actor_id,action,target_id,metadata)
       VALUES($1,$2,$3,'cms.media_quarantine_uploaded',$4,
       jsonb_build_object('sha256',$5::text,'size',$6::bigint,'state','quarantined'))`,
      [randomUUID(),actor.siteId,actor.id,assetId,inspected.sha256,inspected.byteSize],
    );
    await client.query("COMMIT");
    return {assetId,state:"quarantined",blobStatus:"uploaded"};
  }catch(error){
    try{await client.query("ROLLBACK");}catch{}
    // A storage success followed by DB failure can leave a private orphan.
    // Do not delete automatically: operations must reconcile the object.
    throw error;
  }finally{client.release();}
}
