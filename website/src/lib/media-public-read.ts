import "server-only";
import {createHash} from "node:crypto";
import {Pool} from "pg";
import {S3Client,GetObjectCommand,HeadObjectCommand} from "@aws-sdk/client-s3";
import {approvedPublicStoreEndpoint,validatePublicMediaReference} from "./media-delivery-contract";

const featureEnabled=()=>process.env.WEBSITE_MEDIA_PUBLIC_DELIVERY_ENABLED==="true" &&
  process.env.WEBSITE_MEDIA_PUBLIC_READER_GRANTS_VERIFIED==="true";
let pool:Pool|undefined,storage:S3Client|undefined,signature:string|undefined;
function getReader():Pool {
  const connectionString=process.env.WEBSITE_MEDIA_PUBLIC_DATABASE_URL;
  if(!featureEnabled()||!connectionString||!process.env.WEBSITE_CMS_SITE_SLUG||
     !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(process.env.WEBSITE_CMS_SITE_SLUG))
    throw new Error("Public media reader disabled");
  if(!pool)pool=new Pool({connectionString,max:3,connectionTimeoutMillis:2500,
    query_timeout:3500,idleTimeoutMillis:10000});
  return pool;
}
function getStorage():{client:S3Client;bucket:string} {
  if(!featureEnabled())throw new Error("Public media disabled");
  const endpoint=approvedPublicStoreEndpoint(process.env.WEBSITE_MEDIA_PUBLIC_STORAGE_ENDPOINT);
  const bucket=process.env.WEBSITE_MEDIA_PUBLIC_STORAGE_BUCKET;
  const region=process.env.WEBSITE_MEDIA_PUBLIC_STORAGE_REGION;
  const accessKeyId=process.env.WEBSITE_MEDIA_PUBLIC_STORAGE_ACCESS_KEY_ID;
  const secretAccessKey=process.env.WEBSITE_MEDIA_PUBLIC_STORAGE_SECRET_ACCESS_KEY;
  if(!endpoint||!bucket||!/^[a-z0-9][a-z0-9.-]{2,62}$/.test(bucket)||
     !region||!/^[a-z0-9-]{2,40}$/.test(region)||
     !accessKeyId||!secretAccessKey||secretAccessKey.length<16)
    throw new Error("Public media storage not configured");
  const key=createHash("sha256").update([endpoint,bucket,region,accessKeyId,secretAccessKey].join("|")).digest("hex");
  if(!storage||signature!==key){
    storage?.destroy();
    storage=new S3Client({endpoint,region,forcePathStyle:true,
      credentials:{accessKeyId,secretAccessKey},maxAttempts:2});
    signature=key;
  }
  return {client:storage,bucket};
}
/**
 * Read the published-only view on EVERY request. Any withdrawal, missing
 * approval or inaccessible derivative fails closed (never fallback to original).
 * This should run with a dedicated read-only DB role and read-only storage key.
 */
export async function loadPublicApprovedMedia(
  assetId:string,
):Promise<Uint8Array|null> {
  if(!featureEnabled())return null;
  const requestedSite=process.env.WEBSITE_CMS_SITE_SLUG;
  if(!requestedSite||!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(requestedSite))return null;
  try{
    const result=await getReader().query<{
      id:string;storage_key:string;sha256:string;byte_size:string;
    }>(
      `SELECT id,storage_key,sha256,byte_size::text
         FROM website_cms.public_published_media
        WHERE site_slug=$1 AND id=$2 LIMIT 1`,[requestedSite,assetId]);
    if(result.rowCount!==1)return null;
    const valid=validatePublicMediaReference(result.rows[0],assetId);
    if(!valid)return null;
    const {client,bucket}=getStorage();
    const head=await client.send(new HeadObjectCommand({Bucket:bucket,Key:valid.storageKey}),
      {abortSignal:AbortSignal.timeout(5000)});
    if(head.ContentLength!==valid.byteSize||head.Metadata?.sha256!==valid.sha256)return null;
    const content=await client.send(new GetObjectCommand({Bucket:bucket,Key:valid.storageKey}),
      {abortSignal:AbortSignal.timeout(15000)});
    if(!content.Body)return null;
    const chunks:Buffer[]=[];let total=0;
    for await(const part of content.Body as AsyncIterable<Uint8Array>){
      total+=part.byteLength;
      if(total>valid.byteSize)return null;
      chunks.push(Buffer.from(part));
    }
    if(total!==valid.byteSize)return null;
    const bytes=Buffer.concat(chunks,total);
    if(createHash("sha256").update(bytes).digest("hex")!==valid.sha256)return null;
    // Byte content has been decoded/re-encoded and scanner-reviewed prior
    // to publication; this route never reads the source quarantine key.
    return bytes;
  }catch{return null;}
}
