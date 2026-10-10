-- Optional PostgreSQL least-privilege role. Execute with DBA review.
-- This role is intentionally READ ONLY; there are NO grants on drafts, audit or outbox.
-- NOTE: pages/revisions contain drafts; a dedicated SECURITY BARRIER view restricts their exposure.
BEGIN;
CREATE VIEW website_cms.public_published_pages WITH (security_barrier = true) AS
 SELECT s.slug AS site_slug, p.path, p.locale, r.id::text AS id,
        r.revision_number AS revision, r.title, r.description, r.blocks
 FROM website_cms.sites AS s
 JOIN website_cms.pages AS p ON p.site_id = s.id
 JOIN website_cms.page_revisions AS r
 ON r.id = p.current_published_revision_id AND r.page_id = p.id
 WHERE r.state = 'published';
-- DBA must grant SELECT on this view ONLY to the website public reader role.
-- Existing application database roles are NOT modified.
COMMIT;
