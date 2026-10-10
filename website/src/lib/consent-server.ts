import "server-only";
import {randomUUID} from "node:crypto";
import {Pool} from "pg";
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export const CONSENT_COOKIE="website_optional_choice";
export const POLICY_VERSION="v1";
export type ConsentDecision={analytics:boolean;marketing:boolean};
export function parseConsentChoice(value:unknown):ConsentDecision|null {
  if(!value||typeof value!=="object"||Array.isArray(value))return null;
  const x=value as Record<string,unknown>;
  if(typeof x.analytics!=="boolean"||typeof x.marketing!=="boolean")return null;
  return {analytics:x.analytics,marketing:x.marketing};
}
let db:Pool|undefined;
export function consentDatabase():Pool {
  if(process.env.WEBSITE_CONSENT_RECORDS_ENABLED!=="true" ||
     process.env.WEBSITE_PRIVACY_DB_GRANTS_VERIFIED!=="true" ||
     !process.env.WEBSITE_PRIVACY_DATABASE_URL ||
     !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(process.env.WEBSITE_CMS_SITE_SLUG??""))
    throw new Error("Consent records unavailable");
  if(!db)db=new Pool({connectionString:process.env.WEBSITE_PRIVACY_DATABASE_URL,
    max:4,connectionTimeoutMillis:2500,query_timeout:3500,idleTimeoutMillis:10000});
  return db;
}
export async function recordChoice(
  previousId:string|undefined,choice:ConsentDecision,
):Promise<string|null>{
  const client=await consentDatabase().connect();
  try {
    await client.query("BEGIN");
    const site=process.env.WEBSITE_CMS_SITE_SLUG;
    if(previousId&&uuid.test(previousId)){
      await client.query(
        `UPDATE website_cms.consent_choices c SET withdrawn_at=now()
          FROM website_cms.sites s
         WHERE c.id=$1 AND c.site_id=s.id AND s.slug=$2
           AND c.withdrawn_at IS NULL`,[previousId,site]);
    }
    let id:string|null=null;
    if(choice.analytics||choice.marketing){
      id=randomUUID();
      const receipt=await client.query(
        `INSERT INTO website_cms.consent_choices
          (id,site_id,policy_version,analytics_allowed,marketing_allowed,expires_at)
         SELECT $1,s.id,$2,$3,$4,now()+interval '30 days'
           FROM website_cms.sites s WHERE s.slug=$5 RETURNING id`,
        [id,POLICY_VERSION,choice.analytics,choice.marketing,site]);
      if(receipt.rowCount!==1)throw new Error("Site unavailable");
    }
    await client.query("COMMIT");
    return id;
  }catch(error){
    try{await client.query("ROLLBACK");}catch{}
    throw error;
  }finally{client.release();}
}
export async function mayCollectByReceipt(id:string|undefined,purpose:"analytics"|"marketing"):Promise<boolean>{
  if(!id||!uuid.test(id))return false;
  try {
    const result=await consentDatabase().query<{allowed:boolean}>(
      `SELECT c.${purpose==="analytics"?"analytics_allowed":"marketing_allowed"} AS allowed
         FROM website_cms.consent_choices c
         JOIN website_cms.sites s ON s.id=c.site_id
        WHERE c.id=$1 AND s.slug=$2 AND c.withdrawn_at IS NULL
          AND c.expires_at>now() AND c.policy_version=$3`,
      [id,process.env.WEBSITE_CMS_SITE_SLUG,POLICY_VERSION]);
    return result.rowCount===1&&result.rows[0].allowed===true;
  }catch{return false;}
}
