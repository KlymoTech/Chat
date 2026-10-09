#!/usr/bin/env node
/**
 * Single-batch CMS outbox reconciler. Disabled until explicitly activated.
 * At-least-once delivery: HMAC-verified receiver revalidation is idempotent.
 * No content, audit, or outbox records are ever deleted by this worker.
 */
import {Pool} from "pg";
import {
  CMS_EVENTS,cmsRetryDelaySeconds,signCmsInvalidation,verifiedCmsOrigin,
} from "./cms-invalidation-contract.mjs";

const enabled=process.env.WEBSITE_CMS_REVALIDATION_ENABLED==="true";
const origin=verifiedCmsOrigin(process.env.WEBSITE_CANONICAL_ORIGIN);
const secret=process.env.WEBSITE_CMS_REVALIDATION_SECRET;
const siteSlug=process.env.WEBSITE_CMS_SITE_SLUG;
const database=process.env.WEBSITE_CMS_OUTBOX_WORKER_DATABASE_URL;
const validSite=typeof siteSlug==="string" && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(siteSlug);
if(!enabled||!origin||!secret||secret.length<32||!validSite||!database){
  console.error("CMS invalidation worker is disabled or not approved");
  process.exitCode=2;
}else{
  const endpoint=new URL("/api/internal/cms-revalidate",origin);
  const pool=new Pool({connectionString:database,max:2,connectionTimeoutMillis:3000,
    idleTimeoutMillis:5000,query_timeout:15000});
  let acknowledged=0,failed=0;
  try{
    // Bounded batch, no automatic scheduler, and no purge/deletion side effects.
    for(let i=0;i<10;i++){
      const client=await pool.connect();
      try{
        await client.query("BEGIN");
        const result=await client.query(
          "SELECT o.id::text AS event_id,o.event_type,o.attempts,"+
          "o.payload->>'pageId' AS page_id,p.path "+
          "FROM website_cms.outbox o "+
          "JOIN website_cms.sites s ON s.id=o.site_id "+
          "LEFT JOIN website_cms.pages p ON p.id::text=o.payload->>'pageId' "+
          "AND p.site_id=o.site_id "+
          "WHERE s.slug=$1 AND o.event_type=ANY($2::text[]) "+
          "AND o.delivered_at IS NULL AND o.next_attempt_at<=now() "+
          "ORDER BY o.next_attempt_at,o.created_at "+
          "FOR UPDATE OF o SKIP LOCKED LIMIT 1",
          [siteSlug,CMS_EVENTS],
        );
        if(result.rowCount!==1){await client.query("COMMIT");break;}
        const event=result.rows[0];
        let errorCode="invalid_cms_event",ok=false;
        try{
          const envelope=signCmsInvalidation({
            eventId:event.event_id,pageId:event.page_id,
            eventType:event.event_type,path:event.path,
          },secret);
          const response=await fetch(endpoint,{
            method:"POST",redirect:"error",cache:"no-store",
            headers:envelope.headers,body:envelope.body,
            signal:AbortSignal.timeout(5000),
          });
          ok=response.status===204;
          if(!ok)errorCode="http_"+response.status;
        }catch{errorCode="network_or_invalid_event";}
        if(ok){
          await client.query(
            "UPDATE website_cms.outbox SET delivered_at=now(),attempts=attempts+1,"+
            "last_error_code=NULL WHERE id=$1 AND delivered_at IS NULL",
            [event.event_id]);
          acknowledged++;
        }else{
          await client.query(
            "UPDATE website_cms.outbox SET attempts=attempts+1,"+
            "next_attempt_at=now()+($2::integer*interval '1 second'),"+
            "last_error_code=$3 WHERE id=$1 AND delivered_at IS NULL",
            [event.event_id,cmsRetryDelaySeconds(event.attempts+1),errorCode]);
          failed++;
        }
        await client.query("COMMIT");
      }catch(error){
        try{await client.query("ROLLBACK");}catch{}
        console.error("CMS outbox transaction failed:",error?.code??"unknown");
        throw error;
      }finally{client.release();}
    }
    console.log(JSON.stringify({acknowledged,failed,batchLimit:10}));
    if(failed>0)process.exitCode=1;
  }catch{process.exitCode=1;}
  finally{await pool.end();}
}
