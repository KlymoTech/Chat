import "server-only";
import {Pool} from "pg";
import type {CmsActor} from "./cms-editor";
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
let reader:Pool|undefined;
export type AnalyticsDailySummary=Readonly<{day:string;eventName:string;count:number}>;
export async function getAnalyticsSummary(actor:CmsActor):Promise<AnalyticsDailySummary[]> {
  if(process.env.WEBSITE_ANALYTICS_REPORTING_ENABLED!=="true"||
     !process.env.WEBSITE_ANALYTICS_REPORT_DATABASE_URL ||
     process.env.WEBSITE_ANALYTICS_READ_GRANTS_VERIFIED!=="true" ||
     !actor.permissions.includes("cms:read")||!uuid.test(actor.siteId))
    throw new Error("Aggregate reporting is disabled");
  if(!reader)reader=new Pool({connectionString:process.env.WEBSITE_ANALYTICS_REPORT_DATABASE_URL,
    max:2,connectionTimeoutMillis:2500,query_timeout:3500});
  // No person/consent identifier, individual event or raw journey is returned.
  // Suppress low-volume cohorts; reporting window is deliberately bounded.
  const r=await reader.query<{day:string;eventName:string;count:number}>(
    `SELECT to_char(date_trunc('day',received_at AT TIME ZONE 'UTC'),'YYYY-MM-DD') AS day,
            event_name AS "eventName",COUNT(*)::integer AS count
       FROM website_cms.analytics_events
      WHERE site_id=$1 AND received_at>=now()-interval '30 days'
      GROUP BY 1,2 HAVING COUNT(*)>=5
      ORDER BY day DESC,"eventName" ASC LIMIT 200`,
    [actor.siteId]);
  return r.rows;
}
