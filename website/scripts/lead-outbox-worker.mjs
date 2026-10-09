#!/usr/bin/env node
/* Manual, bounded at-least-once lead delivery. Disabled by default.
 * Receiver MUST deduplicate X-Website-Event-Id: a crash after remote 2xx but
 * before commit can cause a retry. No source records are deleted.
 */
import { Pool } from "pg";
import { approvedCrmUrl, retryDelaySeconds, signedLeadEnvelope } from "./lead-worker-contract.mjs";

const url=approvedCrmUrl(process.env.WEBSITE_CRM_WEBHOOK_URL);
const secret=process.env.WEBSITE_CRM_WEBHOOK_SECRET;
const siteSlug=process.env.WEBSITE_CMS_SITE_SLUG;
// Use a separate least-privilege delivery role; never reuse public form credentials.
const dbUrl=process.env.WEBSITE_LEAD_WORKER_DATABASE_URL;
const enabled=process.env.WEBSITE_CRM_DELIVERY_ENABLED==="true" &&
  process.env.WEBSITE_CRM_PRIVACY_APPROVED==="true";
if (!enabled || !url || !secret || secret.length<32 || !siteSlug ||
    !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(siteSlug) || !dbUrl) {
  console.error("Lead delivery disabled or missing approved server-only configuration");
  process.exitCode=2;
} else {
  const pool=new Pool({connectionString:dbUrl,max:2,connectionTimeoutMillis:3000,idleTimeoutMillis:5000});
  let delivered=0,failed=0;
  try {
    for(let i=0;i<10;i++) {
      const client=await pool.connect();
      try {
        await client.query("BEGIN");
        const due=await client.query(
          "SELECT o.id::text,o.site_id::text,o.payload->>'leadId' AS lead_id,o.attempts "+
          "FROM website_cms.outbox o JOIN website_cms.sites s ON s.id=o.site_id "+
          "WHERE s.slug=$1 AND o.event_type='lead.accepted' AND o.delivered_at IS NULL "+
          "AND o.next_attempt_at<=now() ORDER BY o.next_attempt_at,o.created_at "+
          "FOR UPDATE OF o SKIP LOCKED LIMIT 1", [siteSlug]);
        if(due.rowCount!==1){await client.query("COMMIT");break;}
        const event=due.rows[0];
        let errorCode="delivery_error",deliveredNow=false;
        if(event.lead_id && /^[0-9a-f-]{36}$/i.test(event.lead_id)) {
          const rows=await client.query(
            "SELECT id::text,full_name,email,message FROM website_cms.lead_submissions "+
            "WHERE id=$1 AND site_id=$2 LIMIT 1",[event.lead_id,event.site_id]);
          if(rows.rowCount===1){
            const envelope=signedLeadEnvelope(event.id,event.lead_id,rows.rows[0],secret);
            try{
              const response=await fetch(url,{method:"POST",redirect:"error",cache:"no-store",
                headers:envelope.headers,body:envelope.body,signal:AbortSignal.timeout(5000)});
              deliveredNow=response.status>=200 && response.status<300;
              if(!deliveredNow)errorCode="http_"+response.status;
            }catch{errorCode="network_failure";}
          }else{errorCode="missing_lead";}
        }else{errorCode="invalid_event";}
        if(deliveredNow){
          await client.query(
            "UPDATE website_cms.outbox SET delivered_at=now(),attempts=attempts+1,last_error_code=NULL "+
            "WHERE id=$1 AND delivered_at IS NULL",[event.id]);
          delivered++;
        }else{
          const delay=retryDelaySeconds(event.attempts+1);
          await client.query(
            "UPDATE website_cms.outbox SET attempts=attempts+1,"+
            "next_attempt_at=now()+($2::integer*interval '1 second'),last_error_code=$3 "+
            "WHERE id=$1 AND delivered_at IS NULL",[event.id,delay,errorCode]);
          failed++;
        }
        await client.query("COMMIT");
      }catch(error){
        try{await client.query("ROLLBACK");}catch{}
        console.error("Lead outbox transaction failed:",error?.code??"unknown");
        throw error;
      }finally{client.release();}
    }
    console.log(JSON.stringify({delivered,failed,batchMax:10}));
    if(failed>0)process.exitCode=1;
  }catch{process.exitCode=1;}
  finally{await pool.end();}
}
