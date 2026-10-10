-- Chapter 09/38: author-owned blog catalogue, backed by retained CMS revisions.
-- 010 is additive; no auto deletion, source expiry or cascading foreign keys.
BEGIN;
CREATE TABLE IF NOT EXISTS website_cms.blog_entries (
  id uuid PRIMARY KEY,
  page_id uuid NOT NULL UNIQUE REFERENCES website_cms.pages(id) ON DELETE RESTRICT,
  category varchar(60) NOT NULL CHECK (category ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
  tags text[] NOT NULL DEFAULT '{}'::text[],
  created_by_actor_id uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (array_ndims(tags) IS NULL OR array_ndims(tags)=1),
  CHECK (cardinality(tags) <= 8)
);
CREATE INDEX IF NOT EXISTS ix_website_blog_category
  ON website_cms.blog_entries(category);
CREATE VIEW website_cms.public_published_blog_entries
 WITH (security_barrier = true) AS
 SELECT s.slug AS site_slug,p.path,p.locale,r.id::text AS id,
        r.revision_number AS revision,r.title,r.description,r.blocks,
        b.category,b.tags,b.created_at AS blog_created_at
 FROM website_cms.blog_entries b
 JOIN website_cms.pages p ON p.id=b.page_id
 JOIN website_cms.sites s ON s.id=p.site_id
 JOIN website_cms.page_revisions r
   ON r.id=p.current_published_revision_id AND r.page_id=p.id
 WHERE p.trashed_at IS NULL AND r.state='published';
-- DBA must authorize a public read role for SELECT on this view ONLY.
-- Ordinary editors must not receive DELETE or TRUNCATE on blog source.
COMMIT;
