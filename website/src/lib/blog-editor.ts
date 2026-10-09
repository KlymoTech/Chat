import "server-only";
import {randomUUID} from "node:crypto";
import {Pool} from "pg";
import type {CmsActor} from "./cms-editor";
import {parseBlogClassification, type BlogClassification} from "./blog-contract";

const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
let pool:Pool|undefined;
function editorDb():Pool{
  if(!process.env.WEBSITE_CMS_EDITOR_DATABASE_URL)throw new Error("CMS editor database is disabled");
  if(!pool)pool=new Pool({connectionString:process.env.WEBSITE_CMS_EDITOR_DATABASE_URL,
    max:4,connectionTimeoutMillis:3000});
  return pool;
}
function requirePermission(actor:CmsActor,permission:"cms:read"|"cms:draft",pageId:string):void{
  if(!uuid.test(actor.id)||!uuid.test(actor.siteId)||!uuid.test(pageId)||
    !actor.permissions.includes(permission))throw new Error("Unauthorized blog operation");
}
/**
 * Classify an existing content draft. Never updates source revisions or
 * changes the live publication pointer; published classification is frozen
 * pending a reviewed metadata versioning workflow.
 */
export async function classifyBlogDraft(
  actor:CmsActor,pageId:string,untrusted:unknown,
):Promise<BlogClassification>{
  requirePermission(actor,"cms:draft",pageId);
  const metadata=parseBlogClassification(untrusted);
  if(!metadata)throw new Error("Invalid blog category/tags");
  const client=await editorDb().connect();
  try{
    await client.query("BEGIN");
    const page=await client.query(
      "SELECT id FROM website_cms.pages WHERE id=$1 AND site_id=$2 "+
      "AND trashed_at IS NULL AND current_published_revision_id IS NULL "+
      "AND NOT EXISTS(SELECT 1 FROM website_cms.page_revisions r "+
      "WHERE r.page_id=website_cms.pages.id AND r.state IN (\'approved\',\'published\')) FOR UPDATE",
      [pageId,actor.siteId]);
    if(page.rowCount!==1)throw new Error("Only unpublished active pages can change classification");
    await client.query(
      "INSERT INTO website_cms.blog_entries(id,page_id,category,tags,created_by_actor_id) "+
      "VALUES($1,$2,$3,$4,$5) ON CONFLICT(page_id) "+
      "DO UPDATE SET category=EXCLUDED.category,tags=EXCLUDED.tags",
      [randomUUID(),pageId,metadata.category,metadata.tags,actor.id],
    );
    await client.query(
      "INSERT INTO website_cms.audit_events(id,site_id,actor_id,action,target_id,metadata) "+
      "VALUES($1,$2,$3,'cms.blog_classified',$4,jsonb_build_object('category',$5::text,'tags',$6::text[]))",
      [randomUUID(),actor.siteId,actor.id,pageId,metadata.category,metadata.tags],
    );
    await client.query("COMMIT");
    return metadata;
  }catch(error){
    try{await client.query("ROLLBACK");}catch{}
    throw error;
  }finally{client.release();}
}
export async function getOwnerBlogClassification(
  actor:CmsActor,pageId:string,
):Promise<BlogClassification|null>{
  requirePermission(actor,"cms:read",pageId);
  const result=await editorDb().query<{category:string;tags:string[]}>(
    "SELECT b.category,b.tags FROM website_cms.blog_entries b "+
    "JOIN website_cms.pages p ON p.id=b.page_id "+
    "WHERE p.id=$1 AND p.site_id=$2 LIMIT 1",
    [pageId,actor.siteId],
  );
  const row=result.rows[0];
  return row?parseBlogClassification(row):null;
}
