#!/usr/bin/env node
/**
 * DESTRUCTIVE-TEST-SAFE: only an explicitly opted-in local database named
 * website_test is permitted. Never run against production or shared staging.
 * Runs additive migrations exactly once in a fresh, isolated test database.
 */
import assert from "node:assert/strict";
import { randomUUID, createHash } from "node:crypto";
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { Pool } from "pg";

const raw=process.env.WEBSITE_TEST_DATABASE_URL;
if (process.env.WEBSITE_TEST_DATABASE_ALLOW!=="true" || !raw) {
  throw new Error("Only explicit local website_test databases are permitted");
}
const url=new URL(raw);
if (!["localhost","127.0.0.1"].includes(url.hostname) ||
    url.pathname!=="/website_test" || url.protocol!=="postgres:" && url.protocol!=="postgresql:") {
  throw new Error("Refusing to run migration tests outside local website_test");
}
const pool=new Pool({connectionString:raw,max:2,connectionTimeoutMillis:3000});
const client=await pool.connect();
const dbDir=join(dirname(fileURLToPath(import.meta.url)),"../db");
const migrationFiles=readdirSync(dbDir).filter(name=>/^\d{3}_.+\.sql$/.test(name)).sort();
const expected=Array.from({length:19},(_,index)=>String(index+1).padStart(3,"0"));
assert.deepEqual(migrationFiles.map(x=>x.slice(0,3)),expected,"Migrations 001 through 019 must be contiguous");
const uuid=()=>randomUUID();
const count=async(sql,params=[])=>Number((await client.query(sql,params)).rows[0].total);
async function mustReject(sql,params=[],code="23514"){
  let rejected=false;
  try {await client.query(sql,params);}
  catch(error) {rejected=error?.code===code;}
  assert.equal(rejected,true,"Expected PostgreSQL rejection "+code);
}
try {
  for(const filename of migrationFiles) {
    await client.query(readFileSync(join(dbDir,filename),"utf8"));
  }
  const siteId=uuid(),otherSiteId=uuid(),pageId=uuid(),revisionId=uuid(),authorId=uuid(),reviewerId=uuid();
  const publicId=uuid(),otherPageId=uuid(),otherRevisionId=uuid();
  const slug="acceptance-"+uuid().slice(0,8);
  const otherSlug="acceptance-"+uuid().slice(0,8);
  await client.query("INSERT INTO website_cms.sites(id,slug,name) VALUES($1,$2,'Acceptance site'),($3,$4,'Other tenant')",
    [siteId,slug,otherSiteId,otherSlug]);
  await client.query("INSERT INTO website_cms.pages(id,site_id,path,locale) VALUES($1,$2,'/content/acceptance','en')",
    [pageId,siteId]);
  await client.query("INSERT INTO website_cms.page_revisions(id,page_id,revision_number,state,title,description,blocks,actor_id) "+
    "VALUES($1,$2,1,'draft','Draft content','Not published',$3::jsonb,$4)",
    [revisionId,pageId,JSON.stringify([{type:"paragraph",text:"Not visible"}]),authorId]);
  assert.equal(await count(
    "SELECT COUNT(*) AS total FROM website_cms.public_published_pages WHERE site_slug=$1",[slug]),0,
    "Drafts must not be publicly visible");

  // Editorial approval is a distinct attributable record.
  await client.query("INSERT INTO website_cms.revision_approvals(id,site_id,page_id,revision_id,reviewer_id) "+
    "VALUES($1,$2,$3,$4,$5)",[uuid(),siteId,pageId,revisionId,reviewerId]);
  await client.query("UPDATE website_cms.page_revisions SET state='approved' WHERE id=$1",[revisionId]);
  await mustReject("UPDATE website_cms.page_revisions SET title='Changed retroactively' WHERE id=$1",[revisionId]);
  await mustReject("UPDATE website_cms.page_revisions SET state='archived' WHERE id=$1",[revisionId]);

  await client.query("INSERT INTO website_cms.page_revisions "+
    "(id,page_id,revision_number,state,title,description,blocks,actor_id) "+
    "SELECT $1,page_id,2,'published',title,description,blocks,$2 "+
    "FROM website_cms.page_revisions WHERE id=$3",[publicId,reviewerId,revisionId]);
  await client.query("UPDATE website_cms.pages SET current_published_revision_id=$1 WHERE id=$2",[publicId,pageId]);
  assert.equal(await count(
    "SELECT COUNT(*) AS total FROM website_cms.public_published_pages WHERE site_slug=$1",[slug]),1,
    "Published pointer must be publicly visible");
  assert.equal(await count(
    "SELECT COUNT(*) AS total FROM website_cms.public_published_pages WHERE site_slug=$1",[otherSlug]),0,
    "Published pages must not bleed into other site lookup");

  // FK enforces revision belongs to same page, even on direct SQL changes.
  await client.query("INSERT INTO website_cms.pages(id,site_id,path,locale) VALUES($1,$2,'/content/other','en')",
    [otherPageId,otherSiteId]);
  await client.query("INSERT INTO website_cms.page_revisions(id,page_id,revision_number,state,title,description,blocks,actor_id) "+
    "VALUES($1,$2,1,'published','Other','Other',$3::jsonb,$4)",
    [otherRevisionId,otherPageId,JSON.stringify([{type:"paragraph",text:"Other site"}]),reviewerId]);
  await mustReject("UPDATE website_cms.pages SET current_published_revision_id=$1 WHERE id=$2",
    [otherRevisionId,pageId],"23503");

  // Audits and approvals may be inserted, but never altered or destroyed.
  const auditId=uuid();
  await client.query("INSERT INTO website_cms.audit_events(id,site_id,actor_id,action,target_id) "+
    "VALUES($1,$2,$3,'test.approved',$4)",[auditId,siteId,reviewerId,revisionId]);
  await mustReject("UPDATE website_cms.audit_events SET action='tamper' WHERE id=$1",[auditId]);
  await mustReject("DELETE FROM website_cms.page_revisions WHERE id=$1",[revisionId]);
  await mustReject("DELETE FROM website_cms.revision_approvals WHERE revision_id=$1",[revisionId]);

  // Rollback appends a fresh immutable snapshot, retaining the original.
  const rollbackRevisionId=uuid();
  await client.query("INSERT INTO website_cms.page_revisions "+
    "(id,page_id,revision_number,state,title,description,blocks,seo,actor_id) "+
    "SELECT $1,page_id,3,'published',title,description,blocks,seo,$2 "+
    "FROM website_cms.page_revisions WHERE id=$3 AND state='published'",
    [rollbackRevisionId,reviewerId,publicId]);
  await client.query("UPDATE website_cms.pages SET current_published_revision_id=$1 WHERE id=$2",
    [rollbackRevisionId,pageId]);
  assert.equal(await count(
    "SELECT COUNT(*) AS total FROM website_cms.page_revisions WHERE page_id=$1",[pageId]),3,
    "Rollback must preserve originals and append a new published snapshot");
  assert.equal(await count(
    "SELECT COUNT(*) AS total FROM website_cms.public_published_pages WHERE site_slug=$1",[slug]),1);
  // Blog metadata remains attached to the page, not to ephemeral search records.
  // Public blog discovery must use the live published revision pointer.
  await client.query("INSERT INTO website_cms.blog_entries(id,page_id,category,tags,created_by_actor_id) "+
    "VALUES($1,$2,'guidance',$3::text[],$4)",
    [uuid(),pageId,["guidance","updates"],authorId]);
  assert.equal(await count(
    "SELECT COUNT(*) AS total FROM website_cms.public_published_blog_entries WHERE site_slug=$1",[slug]),1,
    "A published, classified article must be discoverable");
  // Trash must remove public visibility while retaining all source revisions.
  await client.query("UPDATE website_cms.pages SET trashed_at=now(),trashed_by_actor_id=$1,"+
    "trash_reason='Manual editorial removal',trashed_published_revision_id=$2,"+
    "current_published_revision_id=NULL WHERE id=$3",[authorId,rollbackRevisionId,pageId]);
  assert.equal(await count(
    "SELECT COUNT(*) AS total FROM website_cms.public_published_pages WHERE site_slug=$1",[slug]),0);
  assert.equal(await count(
    "SELECT COUNT(*) AS total FROM website_cms.page_revisions WHERE page_id=$1",[pageId]),3);
  assert.equal(await count(
    "SELECT COUNT(*) AS total FROM website_cms.public_published_blog_entries WHERE site_slug=$1",[slug]),0,
    "Trashed articles must not appear in blog discovery");
  await client.query("UPDATE website_cms.pages SET current_published_revision_id=$1 WHERE id=$2",
    [publicId,pageId]);
  assert.equal(await count(
    "SELECT COUNT(*) AS total FROM website_cms.public_published_pages WHERE site_slug=$1",[slug]),0,
    "Defense-in-depth public view must still exclude trashed records");
  await client.query("UPDATE website_cms.pages SET trashed_at=NULL,trashed_by_actor_id=NULL,"+
    "trash_reason=NULL,trashed_published_revision_id=NULL,current_published_revision_id=NULL "+
    "WHERE id=$1",[pageId]);
  assert.equal(await count(
    "SELECT COUNT(*) AS total FROM website_cms.public_published_pages WHERE site_slug=$1",[slug]),0,
    "Restore from trash must not silently republish");

  const leadId=uuid(),eventId=uuid(),idempotencyKey=uuid();
  const fingerprint=createHash("sha256").update("Visitor\nvisitor@example.org\nContact us\ntrue").digest("hex");
  await client.query("BEGIN");
  await client.query("INSERT INTO website_cms.lead_submissions "+
    "(id,site_id,idempotency_key,full_name,email,message,privacy_acknowledged,payload_sha256) "+
    "VALUES($1,$2,$3,'Visitor','visitor@example.org','Contact us',true,$4)",
    [leadId,siteId,idempotencyKey,fingerprint]);
  await client.query("INSERT INTO website_cms.outbox(id,site_id,event_type,payload) "+
    "VALUES($1,$2,'lead.accepted',jsonb_build_object('leadId',$3::text))",
    [eventId,siteId,leadId]);
  await client.query("COMMIT");
  assert.equal(await count("SELECT COUNT(*) AS total FROM website_cms.outbox "+
    "WHERE id=$1 AND payload->>'leadId'=$2",[eventId,leadId]),1);
  await mustReject("INSERT INTO website_cms.lead_submissions "+
    "(id,site_id,idempotency_key,full_name,email,message,privacy_acknowledged,payload_sha256) "+
    "VALUES($1,$2,$3,'Visitor','visitor@example.org','Contact us',true,$4)",
    [uuid(),siteId,idempotencyKey,fingerprint],"23505");

  // Deterministic concurrent-safe per-site quota predicate; a fourth attempt is denied.
  const bucket="a".repeat(64);
  const counterSQL="INSERT INTO website_cms.lead_rate_windows "+
    "(site_id,window_start,dimension,subject_hash,accepted_count) "+
    "VALUES($1,date_trunc('hour',now()),'contact',$2,1) "+
    "ON CONFLICT(site_id,window_start,dimension,subject_hash) "+
    "DO UPDATE SET accepted_count=website_cms.lead_rate_windows.accepted_count+1 "+
    "WHERE website_cms.lead_rate_windows.accepted_count < $3 RETURNING accepted_count";
  for(let attempt=1;attempt<=4;attempt++){
    const result=await client.query(counterSQL,[siteId,bucket,3]);
    assert.equal(result.rowCount,attempt<=3?1:0,"Quota did not reject attempt "+attempt);
  }

  // Chapter 8.4: media records remain unavailable until real bytes are scanned.
  const mediaId=uuid();
  await client.query(
    "INSERT INTO website_cms.media_assets("+
    "id,site_id,created_by_actor_id,original_filename,claimed_mime,"+
    "claimed_sha256,claimed_byte_size,quarantine_key,alt_default,rights_statement,provenance) "+
    "VALUES($1,$2,$3,\'illustration.webp\',\'image/webp\',$4,4096,$5,"+
    "\'Page illustration\',\'Original rights confirmed\',"+
    "\'{\"source\":\"original\",\"credit\":\"Team\"}\'::jsonb)",
    [mediaId,siteId,authorId,"a".repeat(64),"quarantine/"+siteId+"/"+mediaId+"/original"]);
  assert.equal(await count(
    "SELECT COUNT(*) AS total FROM website_cms.media_assets "+
    "WHERE site_id=$1 AND state=\'quarantined\' AND blob_status=\'not_uploaded\'",
    [siteId]),1,"New manifest must not be publicly usable");
  await mustReject(
    "UPDATE website_cms.media_assets SET state=\'approved\' WHERE id=$1",
    [mediaId],"23514");
  await client.query(
    "INSERT INTO website_cms.media_usages(site_id,asset_id,page_id,revision_id) "+
    "VALUES($1,$2,$3,$4)",[siteId,mediaId,pageId,publicId]);
  await mustReject(
    "INSERT INTO website_cms.media_usages(site_id,asset_id,page_id,revision_id) "+
    "VALUES($1,$2,$3,$4)",[otherSiteId,mediaId,otherPageId,otherRevisionId],"23503");
  // Processing evidence columns added by 012 must exist before activation.
  const mediaEvidence=await client.query(
    "SELECT sanitized_key,sanitized_sha256,sanitized_byte_size,scan_engine,inspected_at "+
    "FROM website_cms.media_assets WHERE id=$1",[mediaId]);
  assert.equal(mediaEvidence.rows.length,1,"Media fixture should survive migration");
  assert.equal(mediaEvidence.rows[0].sanitized_key,null,
    "Unscanned media must never have a sanitized candidate");
  assert.equal(mediaEvidence.rows[0].inspected_at,null,
    "Unscanned media must remain uninspected");
  // Publication requires a distinct explicit action after independent review.
  const privateMedia=await client.query(
    "SELECT published_at,withdrawn_at FROM website_cms.media_assets WHERE id=$1",
    [mediaId]);
  assert.equal(privateMedia.rows.length,1,"Media fixture must persist");
  assert.equal(privateMedia.rows[0].published_at,null,
    "New quarantine media must not have a public publication timestamp");
  assert.equal(await count(
    "SELECT COUNT(*) AS total FROM website_cms.public_published_media WHERE site_slug=$1",
    [slug]),0,"Private, unscanned media must never enter public media index");
  await mustReject(
    "UPDATE website_cms.media_assets SET published_at=now(),published_by_actor_id=$2 WHERE id=$1",
    [mediaId,authorId],"23514");
  // Chapter 17: optional consent receipts are explicit, scoped and revocable.
  const consentId=uuid(),analyticsId=uuid();
  await client.query(
    "INSERT INTO website_cms.consent_choices "+
    "(id,site_id,policy_version,analytics_allowed,marketing_allowed,expires_at) "+
    "VALUES($1,$2,'v1',true,false,now()+interval '30 days')",
    [consentId,siteId]);
  await client.query(
    "INSERT INTO website_cms.analytics_events "+
    "(id,site_id,consent_id,event_name,action_key,route_path) "+
    "VALUES($1,$2,$3,'cta_click','cta_contact','/contact')",
    [analyticsId,siteId,consentId]);
  await mustReject(
    "INSERT INTO website_cms.analytics_events "+
    "(id,site_id,consent_id,event_name,action_key,route_path) "+
    "VALUES($1,$2,$3,'form_values','email_user','/contact')",
    [uuid(),siteId,consentId],"23514");
  await mustReject(
    "INSERT INTO website_cms.analytics_events "+
    "(id,site_id,consent_id,event_name,action_key,route_path) "+
    "VALUES($1,$2,$3,'cta_click','cta_contact','/contact')",
    [uuid(),otherSiteId,consentId],"23503");
  // New migration 017 rejects fabricated event/action pairs at the DB layer.
  await mustReject(
    "INSERT INTO website_cms.analytics_events "+
    "(id,site_id,consent_id,event_name,action_key,route_path) "+
    "VALUES($1,$2,$3,'faq_open','cta_contact','/contact')",
    [uuid(),siteId,consentId],"23514");
  await client.query(
    "INSERT INTO website_cms.analytics_events "+
    "(id,site_id,consent_id,event_name,action_key,route_path) "+
    "VALUES($1,$2,$3,'faq_open',$4,'/contact')",
    [uuid(),siteId,consentId,
      "faq_550e8400-e29b-41d4-a716-446655440000_0"]);
  await client.query(
    "UPDATE website_cms.consent_choices SET withdrawn_at=now() WHERE id=$1",
    [consentId]);
  assert.equal(await count(
    "SELECT COUNT(*) AS total FROM website_cms.consent_choices "+
    "WHERE id=$1 AND withdrawn_at IS NULL",[consentId]),0,
    "Withdrawn consent must no longer be current");
  // Chapter 45: immutable, private automation revisions. Never executed.
  const automationId=uuid(),automationVersionId=uuid();
  const graph={title:"Synthetic internal review",nodes:[
    {id:"start",type:"trigger",event:"lead_accepted",next:"exit"},
    {id:"exit",type:"exit"},
  ]};
  await client.query(
    "INSERT INTO website_cms.automation_definitions "+
    "(id,site_id,owner_actor_id,title) VALUES($1,$2,$3,$4)",
    [automationId,siteId,authorId,graph.title]);
  await client.query(
    "INSERT INTO website_cms.automation_versions "+
    "(id,site_id,definition_id,version,definition,created_by_actor_id) "+
    "VALUES($1,$2,$3,1,$4::jsonb,$5)",
    [automationVersionId,siteId,automationId,JSON.stringify(graph),authorId]);
  await mustReject(
    "UPDATE website_cms.automation_versions SET version=2 WHERE id=$1",
    [automationVersionId],"23514");
  await mustReject(
    "INSERT INTO website_cms.automation_versions "+
    "(id,site_id,definition_id,version,definition,created_by_actor_id) "+
    "VALUES($1,$2,$3,2,$4::jsonb,$5)",
    [uuid(),otherSiteId,automationId,JSON.stringify(graph),authorId],"23503");
  // Durable internal-only workflow execution fixture (never real contacts).
  const runId=uuid(),subjectId=uuid(),eventId=uuid(),taskId=uuid();
  const internalContext=JSON.stringify({sourceCategory:"form",marketingConsent:false});
  await client.query(
    "INSERT INTO website_cms.automation_internal_runs "+
    "(id,site_id,definition_id,version,subject_type,subject_id,trigger_event_id,"+
    "context,current_node_id,due_at,expires_at) "+
    "VALUES($1,$2,$3,1,'synthetic',$4,$5,$6::jsonb,'start',now(),"+
    "now()+interval '14 days')",
    [runId,siteId,automationId,subjectId,eventId,internalContext]);
  await mustReject(
    "INSERT INTO website_cms.automation_internal_runs "+
    "(id,site_id,definition_id,version,subject_type,subject_id,trigger_event_id,"+
    "context,current_node_id,due_at,expires_at) "+
    "VALUES($1,$2,$3,1,'synthetic',$4,$5,$6::jsonb,'start',now(),"+
    "now()+interval '14 days')",
    [uuid(),siteId,automationId,subjectId,eventId,internalContext],"23505");
  await mustReject(
    "INSERT INTO website_cms.automation_internal_runs "+
    "(id,site_id,definition_id,version,subject_type,subject_id,trigger_event_id,"+
    "context,current_node_id,due_at,expires_at) "+
    "VALUES($1,$2,$3,1,'synthetic',$4,$5,$6::jsonb,'start',now(),"+
    "now()+interval '14 days')",
    [uuid(),otherSiteId,automationId,uuid(),uuid(),internalContext],"23503");
  await client.query(
    "INSERT INTO website_cms.automation_internal_tasks "+
    "(id,site_id,run_id,node_id,action) "+
    "VALUES($1,$2,$3,'review','review_lead')",
    [taskId,siteId,runId]);
  await mustReject(
    "INSERT INTO website_cms.automation_internal_tasks "+
    "(id,site_id,run_id,node_id,action) "+
    "VALUES($1,$2,$3,'review','review_lead')",
    [uuid(),siteId,runId],"23505");
  await mustReject(
    "INSERT INTO website_cms.automation_internal_tasks "+
    "(id,site_id,run_id,node_id,action) "+
    "VALUES($1,$2,$3,'review_two','review_lead')",
    [uuid(),otherSiteId,runId],"23503");

  await mustReject(
    "UPDATE website_cms.automation_internal_runs "+
    "SET status='completed' WHERE id=$1",[runId],"23514");
  await client.query(
    "UPDATE website_cms.automation_internal_runs SET status='completed',"+
    "finished_at=now(),processed_steps=2 WHERE id=$1",[runId]);
  assert.equal(await count(
    "SELECT COUNT(*) AS total FROM website_cms.automation_internal_runs "+
    "WHERE id=$1 AND status='completed' AND processed_steps=2",[runId]),1,
    "Completed synthetic run should preserve its state and budget");
  // Chapter 59: manual privacy rights case state and immutable minimal evidence.
  const rightsCaseId=uuid(),rightsHistoryId=uuid();
  await client.query(
    "INSERT INTO website_cms.privacy_rights_cases "+
    "(id,site_id,request_kind,created_by_actor_id) "+
    "VALUES($1,$2,'erasure',$3)",
    [rightsCaseId,siteId,authorId]);
  await client.query(
    "INSERT INTO website_cms.privacy_rights_history "+
    "(id,site_id,case_id,revision,actor_id,from_status,to_status,reason_code) "+
    "VALUES($1,$2,$3,1,$4,NULL,'intake','intake_recorded')",
    [rightsHistoryId,siteId,rightsCaseId,authorId]);
  await mustReject(
    "UPDATE website_cms.privacy_rights_history "+
    "SET reason_code='review_requested' WHERE id=$1",
    [rightsHistoryId],"23514");
  await mustReject(
    "INSERT INTO website_cms.privacy_rights_history "+
    "(id,site_id,case_id,revision,actor_id,from_status,to_status,reason_code) "+
    "VALUES($1,$2,$3,2,$4,'intake','verified','identity_confirmed')",
    [uuid(),siteId,rightsCaseId,reviewerId],"23514");
  await mustReject(
    "INSERT INTO website_cms.privacy_rights_history "+
    "(id,site_id,case_id,revision,actor_id,from_status,to_status,reason_code) "+
    "VALUES($1,$2,$3,2,$4,'intake','pending_verification','identity_requested')",
    [uuid(),otherSiteId,rightsCaseId,reviewerId],"23503");
  await client.query(
    "INSERT INTO website_cms.privacy_rights_history "+
    "(id,site_id,case_id,revision,actor_id,from_status,to_status,reason_code) "+
    "VALUES($1,$2,$3,2,$4,'intake','pending_verification','identity_requested')",
    [uuid(),siteId,rightsCaseId,reviewerId]);
  // Chapter 10/SEO: a retired slug must be approved by an independent editor.
  const redirectId=uuid();
  const oldPath="/content/retired-handbook";
  await client.query(
    "INSERT INTO website_cms.content_redirects "+
    "(id,site_id,source_path,target_path,reason_code,requested_by) "+
    "VALUES($1,$2,$3,'/services','replaced_content',$4)",
    [redirectId,siteId,oldPath,authorId]);
  await mustReject(
    "UPDATE website_cms.content_redirects "+
    "SET status='approved',reviewed_by=$2,reviewed_at=now() WHERE id=$1",
    [redirectId,authorId],"23514");
  await mustReject(
    "INSERT INTO website_cms.content_redirects "+
    "(id,site_id,source_path,target_path,reason_code,requested_by) "+
    "VALUES($1,$2,'/content/external','https://untrusted.invalid',"+
    "'slug_change',$3)",
    [uuid(),siteId,authorId],"23514");
  await client.query(
    "UPDATE website_cms.content_redirects "+
    "SET status='approved',reviewed_by=$2,reviewed_at=now() WHERE id=$1",
    [redirectId,reviewerId]);
  assert.equal(await count(
    "SELECT COUNT(*) AS total FROM website_cms.public_approved_content_redirects "+
    "WHERE site_slug=$1 AND source_path=$2 AND target_path='/services'",
    [slug,oldPath]),1,"Approved safe redirect must be publicly visible");
  await mustReject(
    "INSERT INTO website_cms.pages (id,site_id,path) VALUES($1,$2,$3)",
    [uuid(),siteId,oldPath],"23514");
  await client.query(
    "UPDATE website_cms.content_redirects "+
    "SET status='suspended',suspended_at=now() WHERE id=$1",[redirectId]);
  assert.equal(await count(
    "SELECT COUNT(*) AS total FROM website_cms.public_approved_content_redirects "+
    "WHERE site_slug=$1 AND source_path=$2",
    [slug,oldPath]),0,
    "Suspended redirect must be hidden from public lookups");
  console.log(JSON.stringify({database:"website_test",migrations:19,checks:[
    "draft-isolation","site-isolation","published-visibility","revision-immutable",
    "independent-approval-record","audit-append-only","no-revision-delete",
    "cross-page-publication-blocked","published-blog-discovery","rollback-appends-snapshot","trash-invisible","restore-unpublished",
    "blog-trash-exclusion","lead-outbox-atomic-fixture","idempotency-unique","quota-fourth-rejected",
    "media-quarantine-initial","media-no-self-approval","media-usage-site-boundary",
    "unpublished-media-default","media-public-view-excludes-quarantine","no-unapproved-media-publication",
    "anonymous-consent-record","analytics-no-form-values","analytics-site-isolation",
    "analytics-event-action-pair-database-enforced",
    "consent-withdrawn","automation-immutable-revision","automation-site-isolation",
    "synthetic-run-durable","synthetic-enrollment-deduplicated",
    "internal-tasks-idempotent","internal-run-site-scope","completed-run-state-consistent",
    "privacy-rights-immutable-history","privacy-rights-evidence-gate",
    "privacy-rights-cross-tenant-denied","privacy-rights-state-preserved",
    "redirect-self-review-denied","redirect-external-destination-blocked",
    "redirect-approved-visible","redirect-source-reuse-denied",
    "redirect-suspension-hides-public"
  ],status:"passed"}));
} finally {
  client.release();
  await pool.end();
}
