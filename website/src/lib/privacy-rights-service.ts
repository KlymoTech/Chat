import "server-only";
import {randomUUID} from "node:crypto";
import {Pool} from "pg";
import type {CmsActor} from "./cms-editor";
import {validCaseKind,validCaseState,allowedCaseTransition,
  type RightKind,type CaseState,type CaseReason} from "./privacy-rights-contract";

const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
let pool:Pool|undefined;
function storage():Pool{
  if(process.env.WEBSITE_PRIVACY_RIGHTS_ENABLED!=="true"||
     process.env.WEBSITE_PRIVACY_RIGHTS_DB_GRANTS_VERIFIED!=="true"||
     !process.env.WEBSITE_PRIVACY_RIGHTS_DATABASE_URL)
    throw new Error("Privacy rights management is disabled");
  if(!pool)pool=new Pool({
    connectionString:process.env.WEBSITE_PRIVACY_RIGHTS_DATABASE_URL,
    max:3,connectionTimeoutMillis:2500,query_timeout:5000,idleTimeoutMillis:10000,
  });
  return pool;
}
function requirePrivacyOwner(actor:CmsActor):void{
  if(!uuid.test(actor.id)||!uuid.test(actor.siteId)||
     !actor.permissions.includes("cms:privacy"))
    throw new Error("Privacy permission required");
}
export type RightsCaseSummary={
 id:string;requestKind:RightKind;status:CaseState;
 revision:number;createdAt:string;updatedAt:string;
};
export async function listRightsCases(actor:CmsActor):Promise<RightsCaseSummary[]>{
  requirePrivacyOwner(actor);
  const result=await storage().query<RightsCaseSummary>(
    `SELECT id::text,request_kind AS "requestKind",status,revision,
         created_at::text AS "createdAt",updated_at::text AS "updatedAt"
       FROM website_cms.privacy_rights_cases WHERE site_id=$1
      ORDER BY updated_at DESC,id DESC LIMIT 100`,[actor.siteId]);
  return result.rows;
}
/** Owner manually records an opaque case. Identity/provenance stay off-app. */
export async function openRightsCase(actor:CmsActor,kind:RightKind):
Promise<{id:string;revision:1;status:"intake"}>{
  requirePrivacyOwner(actor);
  if(!validCaseKind(kind))throw new Error("Invalid rights request kind");
  const db=storage(),client=await db.connect(),id=randomUUID();
  try{
    await client.query("BEGIN");
    await client.query(
      `INSERT INTO website_cms.privacy_rights_cases
         (id,site_id,request_kind,created_by_actor_id)
       VALUES($1,$2,$3,$4)`,
      [id,actor.siteId,kind,actor.id]);
    await client.query(
      `INSERT INTO website_cms.privacy_rights_history
        (id,site_id,case_id,revision,actor_id,from_status,to_status,reason_code)
       VALUES($1,$2,$3,1,$4,NULL,'intake','intake_recorded')`,
      [randomUUID(),actor.siteId,id,actor.id]);
    await client.query(
      `INSERT INTO website_cms.audit_events
        (id,site_id,actor_id,action,target_id)
       VALUES($1,$2,$3,'cms.privacy_case_intake',$4)`,
      [randomUUID(),actor.siteId,actor.id,id]);
    await client.query("COMMIT");
    return {id,revision:1,status:"intake"};
  }catch(error){
    try{await client.query("ROLLBACK");}catch{}
    throw error;
  }finally{client.release();}
}
const secondReview=new Set<CaseState>([
 "verified","legal_hold","approved","denied","in_execution","fulfilled",
]);
const proofRequired=new Set<CaseState>(["verified","denied","fulfilled"]);
export async function advanceRightsCase(actor:CmsActor,id:string,
  expectedRevision:number,to:CaseState,reason:CaseReason,
  evidenceRef?:string,
):Promise<{id:string;revision:number;status:CaseState}>{
  requirePrivacyOwner(actor);
  if(!uuid.test(id)||!Number.isSafeInteger(expectedRevision)||expectedRevision<1||
     !validCaseState(to)||typeof reason!=="string"||
     (evidenceRef!==undefined&&!uuid.test(evidenceRef))||
     (proofRequired.has(to)&&!evidenceRef))throw new Error("Invalid rights case decision");
  const client=await storage().connect();
  try {
    await client.query("BEGIN");
    const existing=await client.query<{
      status:CaseState;revision:number;created_by_actor_id:string;
    }>(
      `SELECT status,revision,created_by_actor_id::text
         FROM website_cms.privacy_rights_cases
        WHERE id=$1 AND site_id=$2 FOR UPDATE`,[id,actor.siteId]);
    if(existing.rowCount!==1)throw new Error("Case not found");
    const row=existing.rows[0];
    if(row.revision!==expectedRevision)
      throw new Error("Privacy case revision conflict");
    if(!allowedCaseTransition(row.status,to,reason))
      throw new Error("Privacy case transition denied");
    // No self-review for verification, denials, approvals or purported fulfilment.
    if(secondReview.has(to)&&row.created_by_actor_id===actor.id)
      throw new Error("Independent privacy reviewer required");
    // Never allow the same reviewer to verify and then approve, deny,
    // declare execution or attest fulfilment of their own prior decision.
    // A row lock on the case serializes both the history read and append.
    if(secondReview.has(to)){
      const prior=await client.query<{actor_id:string}>(
        `SELECT actor_id::text FROM website_cms.privacy_rights_history
          WHERE site_id=$1 AND case_id=$2
          ORDER BY revision DESC LIMIT 1`,[actor.siteId,id]);
      if(prior.rowCount!==1)throw new Error("Rights case history missing");
      if(prior.rows[0].actor_id===actor.id)
        throw new Error("A second independent reviewer must approve this transition");
    }
    const next=row.revision+1;
    await client.query(
      `UPDATE website_cms.privacy_rights_cases
          SET status=$3,revision=$4,updated_at=now()
        WHERE id=$1 AND site_id=$2 AND revision=$5`,
      [id,actor.siteId,to,next,row.revision]);
    await client.query(
      `INSERT INTO website_cms.privacy_rights_history
        (id,site_id,case_id,revision,actor_id,from_status,to_status,
         reason_code,evidence_ref)
       VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)`,
      [randomUUID(),actor.siteId,id,next,actor.id,row.status,to,reason,
       evidenceRef??null]);
    await client.query(
      `INSERT INTO website_cms.audit_events
        (id,site_id,actor_id,action,target_id,metadata)
       VALUES($1,$2,$3,'cms.privacy_case_advanced',$4,
         jsonb_build_object('revision',$5::integer,'status',$6::text))`,
      [randomUUID(),actor.siteId,actor.id,id,next,to]);
    await client.query("COMMIT");
    return {id,revision:next,status:to};
  }catch(error){
    try{await client.query("ROLLBACK");}catch{}
    throw error;
  }finally{client.release();}
}

export type RightsCaseHistory=Readonly<{
 revision:number;fromStatus:CaseState|null;toStatus:CaseState;
 reasonCode:CaseReason|"intake_recorded";recordedAt:string;
 evidenceLinked:boolean;
}>;
/** Expose an actor-redacted, evidence-redacted immutable case history. */
export async function readRightsCaseHistory(actor:CmsActor,id:string):
Promise<RightsCaseHistory[]|null>{
  requirePrivacyOwner(actor);
  if(!uuid.test(id))throw new Error("Invalid rights case ID");
  const allowed=await storage().query(
    `SELECT id FROM website_cms.privacy_rights_cases
       WHERE site_id=$1 AND id=$2`,[actor.siteId,id]);
  if(allowed.rowCount!==1)return null;
  const result=await storage().query<RightsCaseHistory>(
    `SELECT revision,
           from_status AS "fromStatus",to_status AS "toStatus",
           reason_code AS "reasonCode",recorded_at::text AS "recordedAt",
           (evidence_ref IS NOT NULL) AS "evidenceLinked"
      FROM website_cms.privacy_rights_history
     WHERE site_id=$1 AND case_id=$2
     ORDER BY revision ASC LIMIT 200`,[actor.siteId,id]);
  return result.rows;
}
