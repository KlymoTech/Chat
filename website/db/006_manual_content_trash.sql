-- Chapter 38: no automated expiry, source-content purge, or destructive cron.
BEGIN;
ALTER TABLE website_cms.pages
 ADD COLUMN IF NOT EXISTS trashed_at timestamptz,
 ADD COLUMN IF NOT EXISTS trashed_by_actor_id uuid,
 ADD COLUMN IF NOT EXISTS trash_reason varchar(500),
 ADD COLUMN IF NOT EXISTS trashed_published_revision_id uuid;
ALTER TABLE website_cms.pages ADD CONSTRAINT website_page_trash_fields_complete CHECK (
 (trashed_at IS NULL AND trashed_by_actor_id IS NULL AND trash_reason IS NULL AND trashed_published_revision_id IS NULL)
 OR (trashed_at IS NOT NULL AND trashed_by_actor_id IS NOT NULL AND trash_reason IS NOT NULL
     AND length(trim(trash_reason)) BETWEEN 10 AND 500)
);
ALTER TABLE website_cms.pages ADD CONSTRAINT website_trashed_revision_belongs_to_page
 FOREIGN KEY (id,trashed_published_revision_id)
 REFERENCES website_cms.page_revisions(page_id,id) DEFERRABLE INITIALLY DEFERRED;
-- Defense in depth: don't show trashed pages, even if a pointer were mistakenly retained.
CREATE OR REPLACE VIEW website_cms.public_published_pages
 WITH (security_barrier = true) AS
 SELECT s.slug AS site_slug, p.path, p.locale, r.id::text AS id,
        r.revision_number AS revision, r.title, r.description, r.blocks
 FROM website_cms.sites AS s
 JOIN website_cms.pages AS p ON p.site_id=s.id
 JOIN website_cms.page_revisions AS r
   ON r.id=p.current_published_revision_id AND r.page_id=p.id
 WHERE r.state='published' AND p.trashed_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_website_cms_trashed_pages
 ON website_cms.pages(site_id,trashed_at) WHERE trashed_at IS NOT NULL;
-- No DELETE, TTL, purge scheduler, or automatic source-removal logic is created.
COMMIT;
