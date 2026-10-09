import "server-only";
import {S3Client,PutObjectCommand,HeadObjectCommand} from "@aws-sdk/client-s3";
import {createHash} from "node:crypto";
import type {VerifiedQuarantineBytes} from "./media-bytes";

type StoreConfig={endpoint:string;bucket:string;region:string;accessKeyId:string;secretAccessKey:string};
export function readQuarantineStoreConfig(env:NodeJS.ProcessEnv):StoreConfig|null {
  if(env.WEBSITE_MEDIA_UPLOAD_ENABLED!=="true")return null;
  const endpoint=env.WEBSITE_MEDIA_STORAGE_ENDPOINT;
  const bucket=env.WEBSITE_MEDIA_STORAGE_BUCKET;
  const region=env.WEBSITE_MEDIA_STORAGE_REGION;
  const accessKeyId=env.WEBSITE_MEDIA_STORAGE_ACCESS_KEY_ID;
  const secretAccessKey=env.WEBSITE_MEDIA_STORAGE_SECRET_ACCESS_KEY;
  if(!endpoint||!bucket||!region||!accessKeyId||!secretAccessKey||
     !/^[a-z0-9][a-z0-9.-]{2,62}$/.test(bucket) ||
     !/^[a-z0-9-]{2,40}$/.test(region) ||
     accessKeyId.length<3||secretAccessKey.length<16)return null;
  try {
    const url=new URL(endpoint);
    const local=env.NODE_ENV==="development" &&
      env.WEBSITE_MEDIA_STORAGE_LOCAL_DEV==="true" &&
      ["localhost","127.0.0.1"].includes(url.hostname);
    if(url.protocol!=="https:" && !(local&&url.protocol==="http:"))return null;
    if(url.username||url.password||url.search||url.hash||url.pathname!=="/")return null;
    // Production stores must be operator-configured DNS hosts. Local-only
    // development may use localhost; never use private IP/metadata endpoints.
    if(!local && (!url.hostname.includes(".") ||
      !/^[a-z0-9.-]+$/.test(url.hostname) ||
      /^[0-9]+(?:[.][0-9]+){3}$/.test(url.hostname) ||
      url.hostname.endsWith(".local") ||
      url.hostname.endsWith(".localhost") ||
      url.hostname.endsWith(".internal") ||
      url.hostname.endsWith(".test") ||
      url.hostname.endsWith(".example")))return null;
    return {endpoint:url.origin,bucket,region,accessKeyId,secretAccessKey};
  }catch{return null;}
}

let client:S3Client|undefined;
let signature:string|undefined;
function storageClient(config:StoreConfig):S3Client {
  const fingerprint=createHash("sha256").update(config.secretAccessKey).digest("hex");
  const key=[config.endpoint,config.region,config.accessKeyId,config.bucket,fingerprint].join("|");
  if(!client||signature!==key){
    client?.destroy();
    client=new S3Client({
      region:config.region,
      endpoint:config.endpoint,
      forcePathStyle:true,
      credentials:{accessKeyId:config.accessKeyId,secretAccessKey:config.secretAccessKey},
      maxAttempts:2,
    });
    signature=key;
  }
  return client;
}

/** Private object write only. No ACL, public URL, listing or signed download. */
export async function putQuarantineObject(
  key:string,bytes:Uint8Array,validated:VerifiedQuarantineBytes,
):Promise<void> {
  const config=readQuarantineStoreConfig(process.env);
  if(!config)throw new Error("Quarantine object storage is disabled");
  if(!/^quarantine\/[0-9a-f-]{36}\/[0-9a-f-]{36}\/original$/.test(key))
    throw new Error("Invalid quarantine object key");
  const s3=storageClient(config);
  const body=Buffer.from(bytes.buffer,bytes.byteOffset,bytes.byteLength);
  const signal=AbortSignal.timeout(20000);
  await s3.send(new PutObjectCommand({
    Bucket:config.bucket,Key:key,Body:body,
    ContentType:"application/octet-stream",
    CacheControl:"private, no-store",
    ChecksumSHA256:Buffer.from(validated.sha256,"hex").toString("base64"),
    Metadata:{sha256:validated.sha256,purpose:"unreviewed-quarantine"},
  }),{abortSignal:signal});
  const head=await s3.send(new HeadObjectCommand({
    Bucket:config.bucket,Key:key,
  }),{abortSignal:AbortSignal.timeout(5000)});
  if(head.ContentLength!==validated.byteSize ||
     head.Metadata?.sha256!==validated.sha256)
    throw new Error("Object-store acknowledgement does not match verified manifest");
}
