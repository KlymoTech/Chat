import "server-only";
import {randomUUID} from "node:crypto";
import type {PoolClient} from "pg";
import {consentDatabase,POLICY_VERSION} from "./consent-server";
import type {AnalyticsEvent} from "./analytics-contract";
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/** A browser event is never authoritative proof of a form lead or sale. */
export async function recordOptionalAnalytics(
  receiptId:string|undefined,event:AnalyticsEvent,
):Promise<boolean>{
  if(process.env.WEBSITE_ANALYTICS_COLLECTION_ENABLED!=="true" ||
     !receiptId||!uuid.test(receiptId))return false;
  let client:PoolClient|undefined;
  try{
    client=await consentDatabase().connect();
    await client.query("BEGIN");
    // Lock consent so a withdrawal and event cannot race across commits.
    const existing=await client.query<{site_id:string}>(
      `SELECT c.site_id::text
         FROM website_cms.consent_choices c
         JOIN website_cms.sites s ON s.id=c.site_id
        WHERE c.id=$1 AND s.slug=$2 AND c.analytics_allowed=true
          AND c.withdrawn_at IS NULL AND c.expires_at>now()
          AND c.policy_version=$3 FOR UPDATE OF c`,
      [receiptId,process.env.WEBSITE_CMS_SITE_SLUG,POLICY_VERSION]);
    if(existing.rowCount!==1){await client.query("ROLLBACK");return false;}
    const siteId=existing.rows[0].site_id;
    // Cap to 30 events/minute per anonymous receipt; no fingerprint/IP required.
    const counter=await client.query(
      `INSERT INTO website_cms.analytics_rate_windows
        (site_id,consent_id,window_start,accepted_count)
       VALUES($1,$2,date_trunc('minute',now()),1)
       ON CONFLICT(site_id,consent_id,window_start)
       DO UPDATE SET accepted_count=website_cms.analytics_rate_windows.accepted_count+1
         WHERE website_cms.analytics_rate_windows.accepted_count<30
       RETURNING accepted_count`,[siteId,receiptId]);
    if(counter.rowCount!==1){await client.query("ROLLBACK");return false;}
    const result=await client.query(
      `INSERT INTO website_cms.analytics_events(
         id,site_id,consent_id,event_name,action_key,route_path)
       VALUES($1,$2,$3,$4,$5,$6) RETURNING id`,
      [randomUUID(),siteId,receiptId,event.eventName,event.actionKey,event.routePath]);
    if(result.rowCount!==1)throw new Error("Analytics write missing");
    await client.query("COMMIT");
    return true;
  }catch{
    // Optional tracking never crashes a public route when grants, DNS or DB are missing.
    if(client)try{await client.query("ROLLBACK");}catch{}
    return false;
  }finally{client?.release();}
}
