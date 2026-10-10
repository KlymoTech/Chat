#!/usr/bin/env node
/** One-shot, operator-enabled private scanner dispatch. No automatic schedule.
 * Source manifest remains durable until a successful inspection; failed rows
 * are left quarantined for a later retry or manual security investigation. */
import {createHmac} from "node:crypto";
import {Pool} from "pg";
import {verifiedCmsOrigin} from "./cms-invalidation-contract.mjs";

const origin=verifiedCmsOrigin(process.env.WEBSITE_CANONICAL_ORIGIN);
const secret=process.env.WEBSITE_MEDIA_SCAN_WORKER_SECRET;
const dbUrl=process.env.WEBSITE_MEDIA_SCAN_DISPATCH_DATABASE_URL;
const slug=process.env.WEBSITE_CMS_SITE_SLUG;
if(process.env.WEBSITE_MEDIA_SCAN_ENABLED!=="true" ||
   process.env.WEBSITE_MEDIA_SCANNER_DB_ROLE_VERIFIED!=="true" ||
   !origin||!secret||secret.length<32||!dbUrl||!slug||
   !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug)){
  console.error("Private scanner dispatch is disabled");
  process.exitCode=2;
}else{
  const db=new Pool({connectionString:dbUrl,max:1,
    connectionTimeoutMillis:3000,query_timeout:5000});
  let inspected=0,failed=0;
  try{
    const waiting=await db.query(
      `SELECT m.site_id::text AS site_id,m.id::text AS asset_id
         FROM website_cms.media_assets m
         JOIN website_cms.sites s ON s.id=m.site_id
        WHERE s.slug=$1 AND m.state='quarantined'
          AND m.blob_status='uploaded' AND m.scanned_at IS NULL
        ORDER BY m.created_at ASC LIMIT 5`,[slug]);
    for(const row of waiting.rows){
      const body=JSON.stringify({siteId:row.site_id,assetId:row.asset_id});
      const timestamp=Math.floor(Date.now()/1000).toString();
      const signature=createHmac("sha256",secret)
        .update(timestamp+"."+body).digest("hex");
      try{
        const response=await fetch(new URL("/api/internal/media/inspect",origin),{
          method:"POST",redirect:"error",cache:"no-store",
          headers:{"Content-Type":"application/json",
            "X-Media-Scan-Timestamp":timestamp,
            "X-Media-Scan-Signature":"sha256="+signature},
          body,signal:AbortSignal.timeout(60000),
        });
        if(response.ok)inspected++;else failed++;
      }catch{failed++;}
    }
    console.log(JSON.stringify({inspected,failed,selected:waiting.rowCount}));
    if(failed)process.exitCode=1;
  }catch(error){
    console.error("Private scan dispatcher unavailable:",error?.code??"unknown");
    process.exitCode=1;
  }finally{await db.end();}
}
