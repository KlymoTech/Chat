import "server-only";
import {randomUUID} from "node:crypto";
import {Pool} from "pg";
import type {CmsActor} from "./cms-editor";
import {planInternalAutomationStep,type TrustedInternalContext}
  from "./internal-automation-engine";
import {validateAutomation} from "./automation-contract";

const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
let pool:Pool|undefined;
function db():Pool{
  if(process.env.WEBSITE_AUTOMATION_INTERNAL_RUNS_ENABLED!=="true"||
     process.env.WEBSITE_AUTOMATION_RUN_DB_ROLE_VERIFIED!=="true"||
     !process.env.WEBSITE_AUTOMATION_RUN_DATABASE_URL)
    throw new Error("Internal automation runs disabled");
  if(!pool)pool=new Pool({connectionString:process.env.WEBSITE_AUTOMATION_RUN_DATABASE_URL,
    max:3,connectionTimeoutMillis:3000,query_timeout:5000,idleTimeoutMillis:10000});
  return pool;
}
function requireAutomationOwner(actor:CmsActor){
  if(!uuid.test(actor.id)||!uuid.test(actor.siteId)||
     !actor.permissions.includes("cms:automation"))
    throw new Error("Internal automation owner permission required");
}
/** Enroll only synthetic owner-approved test data, never visitors/customers. */
export async function enrollSyntheticAutomation(
  actor:CmsActor,definitionId:string,fixture:TrustedInternalContext,
):Promise<{runId:string;state:"enrolled"}>{
  requireAutomationOwner(actor);
  if(!uuid.test(definitionId)||!["form","subscription"].includes(fixture.sourceCategory)||
     typeof fixture.marketingConsent!=="boolean")
    throw new Error("Invalid synthetic enrollment");
  const client=await db().connect();
  try{
    await client.query("BEGIN");
    const found=await client.query<{id:string;version:number;definition:unknown}>(
      `SELECT v.id::text AS id,v.version,v.definition
         FROM website_cms.automation_versions v
        WHERE v.site_id=$1 AND v.definition_id=$2
        ORDER BY v.version DESC LIMIT 1`,
      [actor.siteId,definitionId]);
    if(found.rowCount!==1)throw Error("Missing draft");
    const value=found.rows[0],graph=validateAutomation(value.definition);
    if(!graph)throw Error("Draft graph invalid");
    const start=graph.nodes.find(x=>x.type==="trigger");
    if(!start)throw Error("Invalid start");
    const runId=randomUUID();
    const subjectId=randomUUID(),triggerId=randomUUID();
    await client.query(
      `INSERT INTO website_cms.automation_internal_runs
        (id,site_id,definition_id,version,subject_type,subject_id,trigger_event_id,
         context,current_node_id,status,due_at,expires_at)
       VALUES($1,$2,$3,$4,'synthetic',$5,$6,$7::jsonb,$8,'enrolled',
              now(),now()+interval '14 days')`,
      [runId,actor.siteId,definitionId,value.version,subjectId,triggerId,
       JSON.stringify(fixture),start.id]);
    await client.query(
      `INSERT INTO website_cms.audit_events
        (id,site_id,actor_id,action,target_id,metadata)
       VALUES($1,$2,$3,'cms.automation_synthetic_enrolled',$4,
         jsonb_build_object('version',$5::integer,'synthetic',true))`,
      [randomUUID(),actor.siteId,actor.id,runId,value.version]);
    await client.query("COMMIT");
    return {runId,state:"enrolled"};
  }catch(error){
    try{await client.query("ROLLBACK");}catch{}
    throw error;
  }finally{client.release();}
}
export type InternalRunSummary=Readonly<{
 id:string;status:string;currentNodeId:string;dueAt:string;processedSteps:number;
}>;
export async function listInternalAutomationRuns(actor:CmsActor,definitionId:string):
Promise<InternalRunSummary[]>{
  requireAutomationOwner(actor);
  if(!uuid.test(definitionId))throw Error("Invalid workflow ID");
  const result=await db().query<InternalRunSummary>(
    `SELECT id::text,status,current_node_id AS "currentNodeId",
           due_at::text AS "dueAt",processed_steps AS "processedSteps"
       FROM website_cms.automation_internal_runs
      WHERE site_id=$1 AND definition_id=$2 AND subject_type='synthetic'
      ORDER BY created_at DESC LIMIT 50`,[actor.siteId,definitionId]);
  return result.rows;
}
/** One-shot leased-by-transaction progression; no external recipient access. */
export async function advanceDueInternalAutomations():Promise<{
 processed:number;completed:number;waiting:number;failed:number;
}> {
  const actorId=process.env.WEBSITE_AUTOMATION_RUNNER_ACTOR_ID;
  if(process.env.WEBSITE_AUTOMATION_RUNNER_ENABLED!=="true"||
     !actorId||!uuid.test(actorId))throw new Error("Internal runner disabled");
  const client=await db().connect();
  const totals={processed:0,completed:0,waiting:0,failed:0};
  try{
    // Small bounded batch; SKIP LOCKED prevents two workers taking same row.
    await client.query("BEGIN");
    await client.query("SET LOCAL lock_timeout = '2s'");
    const due=await client.query<{
      id:string;site_id:string;definition_id:string;version:number;
      current_node_id:string;processed_steps:number;context:TrustedInternalContext;
      expires_at:string;
    }>(
      `SELECT id::text,site_id::text,definition_id::text,version,
              current_node_id,processed_steps,context,expires_at::text
         FROM website_cms.automation_internal_runs
        WHERE subject_type='synthetic' AND status IN('enrolled','running','waiting')
          AND due_at<=now() AND (claimed_until IS NULL OR claimed_until<now())
        ORDER BY due_at ASC LIMIT 10 FOR UPDATE SKIP LOCKED`);
    for(const run of due.rows){
      const revision=await client.query<{definition:unknown}>(
        `SELECT definition FROM website_cms.automation_versions
          WHERE site_id=$1 AND definition_id=$2 AND version=$3 LIMIT 1`,
        [run.site_id,run.definition_id,run.version]);
      const planned=revision.rowCount===1?
        planInternalAutomationStep(revision.rows[0].definition,run.current_node_id,
          run.context,new Date().toISOString(),run.processed_steps):null;
      const expiresAt=Date.parse(run.expires_at);
      const expired=!Number.isFinite(expiresAt)||expiresAt<=Date.now()||
        Boolean(planned&&Date.parse(planned.dueAt)>expiresAt);
      if(!planned||expired){
        await client.query(
          `UPDATE website_cms.automation_internal_runs
              SET status='failed',finished_at=now(),
                  last_error_code=$2,claimed_by=NULL,claimed_until=NULL
            WHERE id=$1`,[run.id,expired?"expired":"invalid_graph"]);
        totals.failed++;continue;
      }
      if(planned.task){
        await client.query(
          `INSERT INTO website_cms.automation_internal_tasks
             (id,site_id,run_id,node_id,action)
           VALUES($1,$2,$3,$4,$5)
           ON CONFLICT(run_id,node_id) DO NOTHING`,
          [randomUUID(),run.site_id,run.id,planned.nodeId,planned.task]);
      }
      const nextStep=run.processed_steps+1;
      await client.query(
        `INSERT INTO website_cms.automation_run_steps
             (id,site_id,run_id,step_number,node_id,result)
           VALUES($1,$2,$3,$4,$5,$6)`,
        [randomUUID(),run.site_id,run.id,nextStep,planned.nodeId,planned.result]);
      await client.query(
        `UPDATE website_cms.automation_internal_runs
          SET current_node_id=$2,status=$3,due_at=$4,
              processed_steps=$5,claimed_by=NULL,claimed_until=NULL,
              finished_at=CASE WHEN $3='completed' THEN now() ELSE NULL END
          WHERE id=$1`,
        [run.id,planned.nextNodeId,planned.nextStatus,planned.dueAt,nextStep]);
      totals.processed++;
      if(planned.nextStatus==="completed")totals.completed++;
      if(planned.nextStatus==="waiting")totals.waiting++;
    }
    await client.query("COMMIT");
    return totals;
  }catch(error){
    try{await client.query("ROLLBACK");}catch{}
    throw error;
  }finally{client.release();}
}

export type InternalTaskSummary=Readonly<{
 id:string;runId:string;nodeId:string;action:string;state:string;createdAt:string;
}>;
export async function listInternalAutomationTasks(
  actor:CmsActor,definitionId:string,
):Promise<InternalTaskSummary[]>{
  requireAutomationOwner(actor);
  if(!uuid.test(definitionId))throw new Error("Invalid workflow ID");
  const found=await db().query<InternalTaskSummary>(
    `SELECT t.id::text,t.run_id::text AS "runId",t.node_id AS "nodeId",
            t.action,t.state,t.created_at::text AS "createdAt"
       FROM website_cms.automation_internal_tasks t
       JOIN website_cms.automation_internal_runs r
         ON r.id=t.run_id AND r.site_id=t.site_id
      WHERE r.site_id=$1 AND r.definition_id=$2 AND r.subject_type='synthetic'
      ORDER BY t.created_at DESC LIMIT 100`,
    [actor.siteId,definitionId]);
  return found.rows;
}
export async function completeInternalAutomationTask(
  actor:CmsActor,definitionId:string,taskId:string,reason:string,
):Promise<{id:string;state:"done"}>{
  requireAutomationOwner(actor);
  if(!uuid.test(definitionId)||!uuid.test(taskId)||
     typeof reason!=="string"||reason.trim().length<10||reason.trim().length>500)
    throw new Error("Invalid internal task decision");
  const client=await db().connect();
  try {
    await client.query("BEGIN");
    const updated=await client.query(
      `UPDATE website_cms.automation_internal_tasks t SET state='done'
        FROM website_cms.automation_internal_runs r
       WHERE t.id=$1 AND t.site_id=$2 AND t.state='pending'
         AND r.id=t.run_id AND r.site_id=t.site_id
         AND r.definition_id=$3 AND r.subject_type='synthetic'
       RETURNING t.id`,
      [taskId,actor.siteId,definitionId]);
    if(updated.rowCount!==1)throw new Error("Task not pending for this site");
    await client.query(
      `INSERT INTO website_cms.audit_events(
         id,site_id,actor_id,action,target_id,metadata)
       VALUES($1,$2,$3,'cms.automation_internal_task_done',$4,
              jsonb_build_object('reason',$5::text))`,
      [randomUUID(),actor.siteId,actor.id,taskId,reason.trim()]);
    await client.query("COMMIT");
    return {id:taskId,state:"done"};
  }catch(error){
    try{await client.query("ROLLBACK");}catch{}
    throw error;
  }finally{client.release();}
}
