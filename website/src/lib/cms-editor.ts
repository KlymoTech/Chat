import "server-only";
import { randomUUID } from "node:crypto";
import { Pool, type PoolClient } from "pg";

/**
 * Private CMS domain service. Never import into a public API route.
 * Authentication must be performed by a future owner-console gateway, which
 * creates the actor context from a verified server session, never client JSON.
 */
export type CmsActor = Readonly<{
  id: string;
  siteId: string;
  permissions: readonly ("cms:draft" | "cms:publish")[];
}>;
export type CmsBlock =
  | { type: "heading" | "paragraph"; text: string }
  | { type: "callout"; title: string; body: string };
export type DraftDocument = Readonly<{
  title: string;
  description: string;
  blocks: CmsBlock[];
}>;

const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i;
function assertActor(actor: CmsActor, operation: "cms:draft" | "cms:publish"): void {
  if (!UUID.test(actor.id) || !UUID.test(actor.siteId) || !actor.permissions.includes(operation)) {
    throw new Error("CMS access denied");
  }
}
function validateDocument(value: DraftDocument): void {
  if (!value.title.trim() || value.title.length > 180 || value.description.length > 500 ||
      value.blocks.length > 100 || JSON.stringify(value.blocks).length > 100_000)
    throw new Error("Invalid CMS document");
  for (const block of value.blocks) {
    if (block.type === "heading" || block.type === "paragraph") {
      if (typeof block.text !== "string" || !block.text.trim() || block.text.length > 10000)
        throw new Error("Invalid text block");
    } else if (block.type === "callout") {
      if (typeof block.title !== "string" || !block.title.trim() || block.title.length > 180 ||
          typeof block.body !== "string" || block.body.length > 10000)
        throw new Error("Invalid callout");
    } else throw new Error("Unapproved CMS block");
  }
}

let editorPool: Pool | undefined;
function pool(): Pool {
  const connectionString = process.env.WEBSITE_CMS_EDITOR_DATABASE_URL;
  if (!connectionString) throw new Error("CMS editor is not configured");
  if (!editorPool) editorPool = new Pool({ connectionString, max: 5, connectionTimeoutMillis: 3000 });
  return editorPool;
}
async function transaction<T>(work: (client: PoolClient) => Promise<T>): Promise<T> {
  const client = await pool().connect();
  try {
    await client.query("BEGIN");
    const result = await work(client);
    await client.query("COMMIT");
    return result;
  } catch (e) {
    await client.query("ROLLBACK");
    throw e;
  } finally { client.release(); }
}

/** Save a new, never overwritten draft revision. No public visibility change. */
export async function saveDraft(actor: CmsActor, pageId: string, document: DraftDocument): Promise<string> {
  assertActor(actor, "cms:draft");
  if (!UUID.test(pageId)) throw new Error("Invalid page ID");
  validateDocument(document);
  return transaction(async client => {
    const page = await client.query(
      "SELECT id FROM website_cms.pages WHERE id=$1 AND site_id=$2 FOR UPDATE",
      [pageId, actor.siteId]);
    if (page.rowCount !== 1) throw new Error("Page not found");
    const count = await client.query<{next: number}>(
      "SELECT COALESCE(MAX(revision_number),0)+1 AS next FROM website_cms.page_revisions WHERE page_id=$1", [pageId]);
    const id = randomUUID();
    await client.query(
      `INSERT INTO website_cms.page_revisions
       (id,page_id,revision_number,state,title,description,blocks,actor_id)
       VALUES ($1,$2,$3,'draft',$4,$5,$6::jsonb,$7)`,
      [id,pageId,count.rows[0].next,document.title,document.description,JSON.stringify(document.blocks),actor.id]);
    await client.query(
      "INSERT INTO website_cms.audit_events(id,site_id,actor_id,action,target_id) VALUES($1,$2,$3,'cms.draft_saved',$4)",
      [randomUUID(),actor.siteId,actor.id,id]);
    return id;
  });
}

/**
 * Publish a separately approved revision as a NEW immutable published revision.
 * Approval itself must be performed by a separate, authenticated review workflow.
 * Never expose this method from an unauthenticated request handler.
 */
export async function publishApproved(actor: CmsActor, pageId: string, approvedRevisionId: string): Promise<string> {
  assertActor(actor, "cms:publish");
  if (!UUID.test(pageId) || !UUID.test(approvedRevisionId)) throw new Error("Invalid CMS IDs");
  return transaction(async client => {
    const page = await client.query(
      "SELECT id FROM website_cms.pages WHERE id=$1 AND site_id=$2 FOR UPDATE",
      [pageId,actor.siteId]);
    if (page.rowCount !== 1) throw new Error("Page not found");
    const source = await client.query<{state:string;actor_id:string}>(
      "SELECT state,actor_id FROM website_cms.page_revisions WHERE id=$1 AND page_id=$2",
      [approvedRevisionId,pageId]);
    if (source.rowCount !== 1 || source.rows[0].state !== "approved")
      throw new Error("Revision has not been approved");
    if (source.rows[0].actor_id === actor.id)
      throw new Error("Publisher must differ from the approved revision author");
    const next = await client.query<{next:number}>(
      "SELECT COALESCE(MAX(revision_number),0)+1 AS next FROM website_cms.page_revisions WHERE page_id=$1",[pageId]);
    const publishedId = randomUUID();
    await client.query(
      `INSERT INTO website_cms.page_revisions
       (id,page_id,revision_number,state,title,description,blocks,seo,actor_id)
       SELECT $1,page_id,$2,'published',title,description,blocks,seo,$3
       FROM website_cms.page_revisions WHERE id=$4 AND page_id=$5`,
      [publishedId,next.rows[0].next,actor.id,approvedRevisionId,pageId]);
    await client.query(
      "UPDATE website_cms.pages SET current_published_revision_id=$1 WHERE id=$2 AND site_id=$3",
      [publishedId,pageId,actor.siteId]);
    await client.query(
      `INSERT INTO website_cms.audit_events(id,site_id,actor_id,action,target_id,metadata)
       VALUES($1,$2,$3,'cms.published',$4,jsonb_build_object('sourceRevisionId',$5::text))`,
      [randomUUID(),actor.siteId,actor.id,publishedId,approvedRevisionId]);
    await client.query(
      `INSERT INTO website_cms.outbox(id,site_id,event_type,payload)
       VALUES($1,$2,'cms.published',jsonb_build_object('pageId',$3::text,'revisionId',$4::text))`,
      [randomUUID(),actor.siteId,pageId,publishedId]);
    return publishedId;
  });
}

/** Roll back by repointing to an existing published snapshot. No historical record is destroyed. */
export async function restorePublished(actor: CmsActor, pageId: string, targetRevisionId: string): Promise<void> {
  assertActor(actor,"cms:publish");
  if (!UUID.test(pageId) || !UUID.test(targetRevisionId)) throw new Error("Invalid CMS IDs");
  await transaction(async client => {
    const page = await client.query(
      "SELECT id FROM website_cms.pages WHERE id=$1 AND site_id=$2 FOR UPDATE",
      [pageId,actor.siteId]);
    if (page.rowCount !== 1) throw new Error("Page not found");
    const target = await client.query(
      "SELECT id FROM website_cms.page_revisions WHERE id=$1 AND page_id=$2 AND state='published'",
      [targetRevisionId,pageId]);
    if (target.rowCount !== 1) throw new Error("Published snapshot not found");
    await client.query(
      "UPDATE website_cms.pages SET current_published_revision_id=$1 WHERE id=$2 AND site_id=$3",
      [targetRevisionId,pageId,actor.siteId]);
    await client.query(
      `INSERT INTO website_cms.audit_events(id,site_id,actor_id,action,target_id)
       VALUES($1,$2,$3,'cms.restored',$4)`,
      [randomUUID(),actor.siteId,actor.id,targetRevisionId]);
    await client.query(
      `INSERT INTO website_cms.outbox(id,site_id,event_type,payload)
       VALUES($1,$2,'cms.restored',jsonb_build_object('pageId',$3::text,'revisionId',$4::text))`,
      [randomUUID(),actor.siteId,pageId,targetRevisionId]);
  });
}
