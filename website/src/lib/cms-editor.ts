import "server-only";
import { randomUUID } from "node:crypto";
import { Pool, type PoolClient } from "pg";
import { normalizeCmsPath } from "./cms-path";
import { attachPublishedMediaUsages } from "./editor-media-links";
import { validBuilderIdentities,validBuilderSection,type BuilderSection,type BuilderIdentity } from "./builder-contract";
import { assertManualPreservationOnly } from "./preservation-contract";

/**
 * Private CMS domain service. Never import into a public API route.
 * Authentication must be performed by a future owner-console gateway, which
 * creates the actor context from a verified server session, never client JSON.
 */
export type CmsActor = Readonly<{
  id: string;
  siteId: string;
  permissions: readonly ("cms:read" | "cms:draft" | "cms:review" | "cms:publish" | "cms:trash" | "cms:restore" | "cms:media" | "cms:media:review" | "cms:media:publish" | "cms:automation" | "cms:privacy" | "cms:redirect")[];
}>;
export type CmsBlock =
  | (BuilderIdentity & { type: "heading" | "paragraph"; text: string })
  | (BuilderIdentity & { type: "callout"; title: string; body: string })
  | (BuilderIdentity & { type: "image"; assetId: string; alt: string; caption: string })
  | BuilderSection;
export type DraftDocument = Readonly<{
  title: string;
  description: string;
  blocks: CmsBlock[];
}>;

const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i;
function assertActor(actor: CmsActor, operation: "cms:read" | "cms:draft" | "cms:review" | "cms:publish" | "cms:trash" | "cms:restore" | "cms:media" | "cms:media:review" | "cms:media:publish" | "cms:automation" | "cms:privacy" | "cms:redirect"): void {
  if (!UUID.test(actor.id) || !UUID.test(actor.siteId) || !actor.permissions.includes(operation)) {
    throw new Error("CMS access denied");
  }
}
function validateDocument(value: DraftDocument): void {
  if (!value.title.trim() || value.title.length > 180 || value.description.length > 500 ||
      value.blocks.length > 100 || JSON.stringify(value.blocks).length > 100_000 ||
      !validBuilderIdentities(value.blocks))
    throw new Error("Invalid CMS document");
  for (const block of value.blocks) {
    if (block.type === "heading" || block.type === "paragraph") {
      if (typeof block.text !== "string" || !block.text.trim() || block.text.length > 10000)
        throw new Error("Invalid text block");
    } else if (block.type === "image") {
      if (!UUID.test(block.assetId) || typeof block.alt !== "string" ||
          !block.alt.trim() || block.alt.length > 300 ||
          typeof block.caption !== "string" || block.caption.length > 500)
        throw new Error("Invalid media image block");
    } else if (block.type === "hero" || block.type === "cta" || block.type === "faq") {
      if (!validBuilderSection(block)) throw new Error("Invalid visual builder section");
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

/** Site-scoped owner listing; private metadata never reaches public routes. */
export async function listOwnerPages(actor: CmsActor): Promise<Array<{
  id: string; path: string; locale: string; publishedRevisionId: string | null;
  publishedTitle: string | null; trashedAt: string | null;
}>> {
  assertActor(actor, "cms:read");
  const result = await pool().query<{
    id: string; path: string; locale: string; publishedRevisionId: string | null;
    publishedTitle: string | null; trashedAt: string | null;
  }>(
    `SELECT p.id::text, p.path, p.locale,
            p.current_published_revision_id::text AS "publishedRevisionId",
            r.title AS "publishedTitle", p.trashed_at::text AS "trashedAt"
       FROM website_cms.pages p
       LEFT JOIN website_cms.page_revisions r ON r.id=p.current_published_revision_id
      WHERE p.site_id=$1 ORDER BY p.created_at DESC, p.path ASC LIMIT 100`,
    [actor.siteId],
  );
  return result.rows;
}

/** Site-scoped editorial history, including drafts. Never use in public CMS paths. */
export async function listOwnerRevisions(actor: CmsActor, pageId: string): Promise<Array<{
  id: string; revision: number; state: string; title: string; description: string;
  blocks: unknown; createdAt: string; authorId: string;
}>> {
  assertActor(actor, "cms:read");
  if (!UUID.test(pageId)) throw new Error("Invalid page ID");
  const result = await pool().query<{
    id: string; revision: number; state: string; title: string; description: string;
    blocks: unknown; createdAt: string; authorId: string;
  }>(
    `SELECT r.id::text AS id, r.revision_number AS revision, r.state,
            r.title, r.description, r.blocks,
            r.created_at::text AS "createdAt", r.actor_id::text AS "authorId"
       FROM website_cms.page_revisions r
       JOIN website_cms.pages p ON p.id=r.page_id
      WHERE p.id=$1 AND p.site_id=$2
      ORDER BY r.revision_number DESC LIMIT 100`,
    [pageId, actor.siteId],
  );
  return result.rows;
}

/** Create an isolated page and its initial draft in one auditable transaction.
 * Does not publish the page or make it visible in public navigation. */
export async function createPage(
  actor: CmsActor, pathInput: string, locale: string, document: DraftDocument,
): Promise<{ pageId: string; revisionId: string }> {
  assertActor(actor, "cms:draft");
  validateDocument(document);
  const path = normalizeCmsPath(pathInput);
  if (!path || !/^[a-z]{2}(?:-[A-Z]{2})?$/.test(locale)) throw new Error("Invalid page route or locale");
  return transaction(async client => {
    const pageId = randomUUID();
    const revisionId = randomUUID();
    const created = await client.query(
      `INSERT INTO website_cms.pages (id,site_id,path,locale)
       SELECT $1,s.id,$2,$3 FROM website_cms.sites s WHERE s.id=$4
       ON CONFLICT(site_id,locale,path) DO NOTHING RETURNING id`,
      [pageId,path,locale,actor.siteId]);
    if (created.rowCount !== 1) throw new Error("Page already exists or site not provisioned");
    await client.query(
      `INSERT INTO website_cms.page_revisions
       (id,page_id,revision_number,state,title,description,blocks,actor_id)
       VALUES($1,$2,1,'draft',$3,$4,$5::jsonb,$6)`,
      [revisionId,pageId,document.title,document.description,JSON.stringify(document.blocks),actor.id]);
    await client.query(
      `INSERT INTO website_cms.audit_events(id,site_id,actor_id,action,target_id)
       VALUES($1,$2,$3,'cms.page_created',$4)`,
      [randomUUID(),actor.siteId,actor.id,pageId]);
    return { pageId, revisionId };
  });
}

/** Save a new, never overwritten draft revision. No public visibility change. */
export async function saveDraft(actor: CmsActor, pageId: string, document: DraftDocument,
  expectedVersion: number): Promise<string> {
  assertActor(actor, "cms:draft");
  if (!UUID.test(pageId)) throw new Error("Invalid page ID");
  validateDocument(document);
  if(!Number.isSafeInteger(expectedVersion)||expectedVersion<1)
    throw new Error("Expected CMS revision is required");
  return transaction(async client => {
    const page = await client.query(
      "SELECT id FROM website_cms.pages WHERE id=$1 AND site_id=$2 AND trashed_at IS NULL FOR UPDATE",
      [pageId, actor.siteId]);
    if (page.rowCount !== 1) throw new Error("Page not found");
    const count = await client.query<{next: number}>(
      "SELECT COALESCE(MAX(revision_number),0)+1 AS next FROM website_cms.page_revisions WHERE page_id=$1", [pageId]);
    if (count.rows[0].next !== expectedVersion+1)
      throw new Error("CMS revision conflict: another editor saved a newer version");
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

/** Review a draft without editing its content. A separate reviewer is required. */
export async function approveDraft(actor: CmsActor, pageId: string, revisionId: string): Promise<string> {
  assertActor(actor, "cms:review");
  if (!UUID.test(pageId) || !UUID.test(revisionId)) throw new Error("Invalid CMS IDs");
  return transaction(async client => {
    const page = await client.query(
      "SELECT id FROM website_cms.pages WHERE id=$1 AND site_id=$2 AND trashed_at IS NULL FOR UPDATE",
      [pageId, actor.siteId]);
    if (page.rowCount !== 1) throw new Error("Page not found");
    const revision = await client.query<{state:string;actor_id:string}>(
      "SELECT state,actor_id FROM website_cms.page_revisions WHERE id=$1 AND page_id=$2 FOR UPDATE",
      [revisionId,pageId]);
    if (revision.rowCount !== 1 || revision.rows[0].state !== "draft")
      throw new Error("Only draft revisions can be approved");
    if (revision.rows[0].actor_id === actor.id)
      throw new Error("Authors cannot approve their own revision");
    const approvalId = randomUUID();
    await client.query(
      `INSERT INTO website_cms.revision_approvals
       (id,site_id,page_id,revision_id,reviewer_id) VALUES($1,$2,$3,$4,$5)`,
      [approvalId,actor.siteId,pageId,revisionId,actor.id]);
    await client.query(
      "UPDATE website_cms.page_revisions SET state='approved' WHERE id=$1 AND page_id=$2 AND state='draft'",
      [revisionId,pageId]);
    await client.query(
      `INSERT INTO website_cms.audit_events(id,site_id,actor_id,action,target_id)
       VALUES($1,$2,$3,'cms.approved',$4)`,
      [randomUUID(),actor.siteId,actor.id,revisionId]);
    return approvalId;
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
      "SELECT id FROM website_cms.pages WHERE id=$1 AND site_id=$2 AND trashed_at IS NULL FOR UPDATE",
      [pageId,actor.siteId]);
    if (page.rowCount !== 1) throw new Error("Page not found");
    const source = await client.query<{state:string;actor_id:string;blocks:CmsBlock[]}>(
      "SELECT state,actor_id,blocks FROM website_cms.page_revisions WHERE id=$1 AND page_id=$2",
      [approvedRevisionId,pageId]);
    if (source.rowCount !== 1 || source.rows[0].state !== "approved")
      throw new Error("Revision has not been approved");
    if (source.rows[0].actor_id === actor.id)
      throw new Error("Publisher must differ from the approved revision author");
    const approval = await client.query<{reviewer_id:string}>(
      `SELECT reviewer_id FROM website_cms.revision_approvals
       WHERE site_id=$1 AND page_id=$2 AND revision_id=$3 LIMIT 1`,
      [actor.siteId,pageId,approvedRevisionId]);
    if (approval.rowCount !== 1 || approval.rows[0].reviewer_id === source.rows[0].actor_id)
      throw new Error("Independent review evidence missing");

    const next = await client.query<{next:number}>(
      "SELECT COALESCE(MAX(revision_number),0)+1 AS next FROM website_cms.page_revisions WHERE page_id=$1",[pageId]);
    const publishedId = randomUUID();
    await client.query(
      `INSERT INTO website_cms.page_revisions
       (id,page_id,revision_number,state,title,description,blocks,seo,actor_id)
       SELECT $1,page_id,$2,'published',title,description,blocks,seo,$3
       FROM website_cms.page_revisions WHERE id=$4 AND page_id=$5`,
      [publishedId,next.rows[0].next,actor.id,approvedRevisionId,pageId]);
    await attachPublishedMediaUsages(client,actor.siteId,pageId,publishedId,source.rows[0].blocks);
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

/** Restore a compatible published snapshot as a NEW publication action.
 * The original snapshot is retained; the live pointer is never silently rewound.
 */
export async function restorePublished(actor: CmsActor, pageId: string, targetRevisionId: string): Promise<string> {
  assertActor(actor,"cms:publish");
  if (!UUID.test(pageId) || !UUID.test(targetRevisionId)) throw new Error("Invalid CMS IDs");
  return transaction(async client => {
    const page = await client.query<{current_published_revision_id:string|null}>(
      "SELECT current_published_revision_id FROM website_cms.pages "+
      "WHERE id=$1 AND site_id=$2 AND trashed_at IS NULL FOR UPDATE",
      [pageId,actor.siteId]);
    if (page.rowCount !== 1) throw new Error("Page not found");
    const target = await client.query<{
      title:string;description:string;blocks:CmsBlock[];seo:Record<string,unknown>;
    }>(
      "SELECT title,description,blocks,seo FROM website_cms.page_revisions "+
      "WHERE id=$1 AND page_id=$2 AND state='published'",
      [targetRevisionId,pageId]);
    if (target.rowCount !== 1) throw new Error("Published snapshot not found");
    // Fail closed on schema-incompatible historical revisions.
    validateDocument({
      title:target.rows[0].title,description:target.rows[0].description,
      blocks:target.rows[0].blocks,
    });
    const next=await client.query<{next:number}>(
      "SELECT COALESCE(MAX(revision_number),0)+1 AS next "+
      "FROM website_cms.page_revisions WHERE page_id=$1",[pageId]);
    const restoredId=randomUUID();
    await client.query(
      `INSERT INTO website_cms.page_revisions
       (id,page_id,revision_number,state,title,description,blocks,seo,actor_id)
       SELECT $1,page_id,$2,'published',title,description,blocks,seo,$3
       FROM website_cms.page_revisions WHERE id=$4 AND page_id=$5 AND state='published'`,
      [restoredId,next.rows[0].next,actor.id,targetRevisionId,pageId]);
    await attachPublishedMediaUsages(client,actor.siteId,pageId,restoredId,target.rows[0].blocks);
    await client.query(
      "UPDATE website_cms.pages SET current_published_revision_id=$1 "+
      "WHERE id=$2 AND site_id=$3",
      [restoredId,pageId,actor.siteId]);
    await client.query(
      `INSERT INTO website_cms.audit_events(id,site_id,actor_id,action,target_id,metadata)
       VALUES($1,$2,$3,'cms.restored',$4,
       jsonb_build_object('sourceRevisionId',$5::text,'previousLiveRevisionId',$6::text))`,
      [randomUUID(),actor.siteId,actor.id,restoredId,targetRevisionId,
        page.rows[0].current_published_revision_id]);
    await client.query(
      `INSERT INTO website_cms.outbox(id,site_id,event_type,payload)
       VALUES($1,$2,'cms.restored',
       jsonb_build_object('pageId',$3::text,'revisionId',$4::text,'sourceRevisionId',$5::text))`,
      [randomUUID(),actor.siteId,pageId,restoredId,targetRevisionId]);
    return restoredId;
  });
}

/**
 * Manually trash a page, without destroying its source or revision history.
 * An authorized human must supply the reason. Public delivery is withdrawn in
 * the same committed transaction that records audit and outbox events.
 */
export async function trashContentPage(actor: CmsActor, pageId: string, reason: string):
  Promise<{operationId: string; state: "trash-queued"}> {
  assertActor(actor, "cms:trash");
  assertManualPreservationOnly(process.env.BLOG_AUTO_DELETE_ENABLED);
  if (!UUID.test(pageId) || typeof reason !== "string" ||
      reason.trim().length < 10 || reason.trim().length > 500) throw new Error("Invalid trash request");
  return transaction(async client => {
    const page = await client.query<{current_published_revision_id: string | null}>(
      "SELECT current_published_revision_id FROM website_cms.pages WHERE id=$1 AND site_id=$2 AND trashed_at IS NULL FOR UPDATE",
      [pageId, actor.siteId],
    );
    if (page.rowCount !== 1) throw new Error("Page not found or already trashed");
    const operationId = randomUUID();
    const previousRevision = page.rows[0].current_published_revision_id;
    await client.query(
      "UPDATE website_cms.pages SET trashed_at=now(),trashed_by_actor_id=$1,trash_reason=$2,trashed_published_revision_id=$3,current_published_revision_id=NULL WHERE id=$4 AND site_id=$5",
      [actor.id, reason.trim(), previousRevision, pageId, actor.siteId],
    );
    await client.query(
      "INSERT INTO website_cms.audit_events(id,site_id,actor_id,action,target_id,metadata) VALUES($1,$2,$3,'cms.trashed',$4,jsonb_build_object('operationId',$5::text,'reason',$6::text,'previousRevisionId',$7::text))",
      [randomUUID(),actor.siteId,actor.id,pageId,operationId,reason.trim(),previousRevision],
    );
    await client.query(
      "INSERT INTO website_cms.outbox(id,site_id,event_type,payload) VALUES($1,$2,'cms.trashed',jsonb_build_object('pageId',$3::text,'operationId',$4::text))",
      [randomUUID(),actor.siteId,pageId,operationId],
    );
    return {operationId,state:"trash-queued" as const};
  });
}

/** Restore the source as an unpublished draft container, never silently republish. */
export async function restoreTrashedContentPage(actor: CmsActor, pageId: string, reason: string):
  Promise<{operationId: string; state: "restored-unpublished"}> {
  assertActor(actor, "cms:restore");
  assertManualPreservationOnly(process.env.BLOG_AUTO_DELETE_ENABLED);
  if (!UUID.test(pageId) || typeof reason !== "string" ||
      reason.trim().length < 10 || reason.trim().length > 500) throw new Error("Invalid restore request");
  return transaction(async client => {
    const page = await client.query<{trashed_published_revision_id: string|null}>(
      "SELECT trashed_published_revision_id FROM website_cms.pages WHERE id=$1 AND site_id=$2 AND trashed_at IS NOT NULL FOR UPDATE",
      [pageId,actor.siteId],
    );
    if (page.rowCount !== 1) throw new Error("Page not found in trash");
    const operationId = randomUUID();
    await client.query(
      "UPDATE website_cms.pages SET trashed_at=NULL,trashed_by_actor_id=NULL,trash_reason=NULL,trashed_published_revision_id=NULL,current_published_revision_id=NULL WHERE id=$1 AND site_id=$2",
      [pageId,actor.siteId],
    );
    await client.query(
      "INSERT INTO website_cms.audit_events(id,site_id,actor_id,action,target_id,metadata) VALUES($1,$2,$3,'cms.restored_from_trash',$4,jsonb_build_object('operationId',$5::text,'reason',$6::text,'previousRevisionId',$7::text))",
      [randomUUID(),actor.siteId,actor.id,pageId,operationId,reason.trim(),page.rows[0].trashed_published_revision_id],
    );
    await client.query(
      "INSERT INTO website_cms.outbox(id,site_id,event_type,payload) VALUES($1,$2,'cms.restored_from_trash',jsonb_build_object('pageId',$3::text,'operationId',$4::text))",
      [randomUUID(),actor.siteId,pageId,operationId],
    );
    return {operationId,state:"restored-unpublished" as const};
  });
}
