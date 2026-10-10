-- Website 1.3: independently reviewed media must ALSO be explicitly published.
-- Additive after 012; preserve all quarantine, audit, usage and source records.
BEGIN;
ALTER TABLE website_cms.media_assets
 ADD COLUMN IF NOT EXISTS published_at timestamptz,
 ADD COLUMN IF NOT EXISTS published_by_actor_id uuid,
 ADD COLUMN IF NOT EXISTS withdrawn_at timestamptz,
 ADD COLUMN IF NOT EXISTS withdrawn_by_actor_id uuid;
ALTER TABLE website_cms.media_assets
 ADD CONSTRAINT website_media_publication_attribution CHECK (
   (published_at IS NULL AND published_by_actor_id IS NULL
     AND withdrawn_at IS NULL AND withdrawn_by_actor_id IS NULL)
   OR
   (published_at IS NOT NULL AND published_by_actor_id IS NOT NULL
     AND state='approved'
     AND ((withdrawn_at IS NULL AND withdrawn_by_actor_id IS NULL)
       OR (withdrawn_at IS NOT NULL AND withdrawn_by_actor_id IS NOT NULL)))
 );
-- SELECT on this security-barrier view must be granted only to a reviewed
-- server-side PUBLIC MEDIA READER role. Never grant access to raw media_assets.
-- The storage key stays inside the server and MUST NOT be returned by its API.
CREATE VIEW website_cms.public_published_media WITH (security_barrier=true) AS
 SELECT s.slug AS site_slug,m.id::text AS id,m.alt_default AS alt,
        m.sanitized_key AS storage_key,
        m.sanitized_sha256 AS sha256,
        m.sanitized_byte_size AS byte_size
 FROM website_cms.sites s
 JOIN website_cms.media_assets m ON m.site_id=s.id
 WHERE m.state='approved' AND m.blob_status='uploaded'
   AND m.reviewed_at IS NOT NULL AND m.reviewed_by_actor_id IS NOT NULL
   AND m.reviewed_by_actor_id<>m.created_by_actor_id
   AND m.scanned_at IS NOT NULL AND m.inspected_at IS NOT NULL
   AND m.sanitized_key LIKE 'processed/%'
   AND m.sanitized_sha256 IS NOT NULL AND m.sanitized_byte_size IS NOT NULL
   AND m.published_at IS NOT NULL AND m.withdrawn_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_website_media_publication
 ON website_cms.media_assets(site_id,published_at,withdrawn_at)
 WHERE state='approved';
-- No public bucket, source download, automatic media purge, or expiry.
COMMIT;
