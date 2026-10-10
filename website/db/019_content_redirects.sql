-- Controlled same-site redirects for retired /content/<slug> routes only.
-- Additive migration; no user-supplied external destinations or URL queries.
BEGIN;
CREATE TABLE IF NOT EXISTS website_cms.content_redirects (
 id uuid PRIMARY KEY,
 site_id uuid NOT NULL REFERENCES website_cms.sites(id),
 source_path varchar(512) NOT NULL,
 target_path varchar(512) NOT NULL,
 reason_code varchar(32) NOT NULL CHECK(reason_code IN
   ('slug_change','consolidated_content','replaced_content')),
 status varchar(12) NOT NULL DEFAULT 'draft'
   CHECK(status IN ('draft','approved','suspended')),
 requested_by uuid NOT NULL,
 reviewed_by uuid,
 created_at timestamptz NOT NULL DEFAULT now(),
 reviewed_at timestamptz,
 suspended_at timestamptz,
 CHECK(source_path ~ '^/content/[a-z0-9]+(-[a-z0-9]+)*$'),
 CHECK(target_path ~ '^/(services|about|contact|resources|blog|privacy|terms|content/[a-z0-9]+(-[a-z0-9]+)*)$'),
 CHECK(source_path <> target_path),
 CHECK(status <> 'approved' OR
   (reviewed_by IS NOT NULL AND reviewed_by <> requested_by
    AND reviewed_at IS NOT NULL AND suspended_at IS NULL)),
 UNIQUE(site_id,source_path),
 UNIQUE(site_id,id)
);
CREATE INDEX IF NOT EXISTS ix_website_redirects_site_status
 ON website_cms.content_redirects(site_id,status,created_at DESC);
-- Show a redirect publicly only if the old URL no longer points to an
-- existing page and its destination is either an application public route
-- or a CMS page whose published pointer still resolves to a published revision.
CREATE OR REPLACE VIEW website_cms.public_approved_content_redirects
 WITH(security_barrier=true) AS
 SELECT s.slug AS site_slug,d.source_path,d.target_path
 FROM website_cms.content_redirects d
 JOIN website_cms.sites s ON s.id=d.site_id
 WHERE d.status='approved'
   AND NOT EXISTS (
      SELECT 1 FROM website_cms.pages p
       WHERE p.site_id=d.site_id AND p.path=d.source_path
   )
   AND (
     d.target_path IN ('/services','/about','/contact','/resources',
                       '/blog','/privacy','/terms')
     OR EXISTS (
       SELECT 1 FROM website_cms.pages p
       JOIN website_cms.page_revisions r
         ON r.id=p.current_published_revision_id AND r.page_id=p.id
       WHERE p.site_id=d.site_id AND p.path=d.target_path
         AND r.state='published'
     )
   );
-- Page creation must not silently reclaim an actively redirected URL.
CREATE OR REPLACE FUNCTION website_cms.reject_active_redirect_page_collision()
RETURNS trigger LANGUAGE plpgsql AS $
BEGIN
 -- Redirect approvals lock this same site row before checking route occupancy.
 -- Serializing both paths closes the page-create/redirect-approval race.
 PERFORM 1 FROM website_cms.sites
  WHERE id=NEW.site_id FOR UPDATE;
 IF EXISTS (
   SELECT 1 FROM website_cms.content_redirects d
    WHERE d.site_id=NEW.site_id AND d.source_path=NEW.path
      AND d.status='approved'
 ) THEN
   RAISE EXCEPTION 'Cannot reuse an approved content redirect source'
     USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_website_content_redirect_collision ON website_cms.pages;
CREATE TRIGGER trg_website_content_redirect_collision
 BEFORE INSERT OR UPDATE OF path,site_id ON website_cms.pages
 FOR EACH ROW EXECUTE FUNCTION website_cms.reject_active_redirect_page_collision();
-- Public runtime database role must receive SELECT on the security-barrier
-- view ONLY (never on content_redirects or private pages/revisions).
-- Operator must verify those role grants and cross-site restrictions first.
COMMIT;
