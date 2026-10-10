-- Website Blueprint 8.4: media manifest/quarantine foundation (NO public blob delivery).
-- Apply after migrations 001-010 only on a backed-up, DBA-reviewed instance.
-- Metadata records are not evidence that bytes exist or passed a content scan.
BEGIN;
CREATE TABLE IF NOT EXISTS website_cms.media_assets (
  id uuid PRIMARY KEY,
  site_id uuid NOT NULL REFERENCES website_cms.sites(id),
  created_by_actor_id uuid NOT NULL,
  original_filename varchar(255) NOT NULL
    CHECK (length(trim(original_filename)) BETWEEN 1 AND 255),
  claimed_mime varchar(60) NOT NULL
    CHECK (claimed_mime IN ('image/jpeg','image/png','image/webp','image/avif')),
  claimed_sha256 char(64) NOT NULL CHECK (claimed_sha256 ~ '^[a-f0-9]{64}$'),
  claimed_byte_size bigint NOT NULL CHECK (claimed_byte_size BETWEEN 1 AND 10485760),
  quarantine_key text NOT NULL UNIQUE CHECK (quarantine_key LIKE 'quarantine/%'),
  alt_default varchar(300) NOT NULL DEFAULT '',
  rights_statement varchar(500) NOT NULL DEFAULT '',
  provenance jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(provenance)='object'),
  blob_status varchar(16) NOT NULL DEFAULT 'not_uploaded'
    CHECK (blob_status IN ('not_uploaded','uploaded')),
  state varchar(16) NOT NULL DEFAULT 'quarantined'
    CHECK (state IN ('quarantined','rejected','approved')),
  detected_mime varchar(60)
    CHECK (detected_mime IS NULL OR detected_mime IN
      ('image/jpeg','image/png','image/webp','image/avif')),
  verified_sha256 char(64) CHECK (verified_sha256 ~ '^[a-f0-9]{64}$'),
  verified_byte_size bigint CHECK (verified_byte_size BETWEEN 1 AND 10485760),
  verified_width integer CHECK (verified_width BETWEEN 1 AND 10000),
  verified_height integer CHECK (verified_height BETWEEN 1 AND 10000),
  scanner_receipt_sha256 char(64)
    CHECK (scanner_receipt_sha256 ~ '^[a-f0-9]{64}$'),
  scanned_at timestamptz,
  reviewed_by_actor_id uuid,
  reviewed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  -- Public use requires independent scan + review; claim fields are insufficient.
  CONSTRAINT website_media_approved_evidence CHECK (
    state <> 'approved' OR (
      blob_status = 'uploaded' AND
      detected_mime IS NOT NULL AND verified_sha256 IS NOT NULL AND
      verified_byte_size IS NOT NULL AND
      detected_mime = claimed_mime AND
      verified_sha256 = claimed_sha256 AND
      verified_byte_size = claimed_byte_size AND
      verified_width IS NOT NULL AND verified_height IS NOT NULL AND
      scanner_receipt_sha256 IS NOT NULL AND scanned_at IS NOT NULL AND
      reviewed_by_actor_id IS NOT NULL AND reviewed_at IS NOT NULL AND
      length(trim(alt_default)) > 0 AND length(trim(rights_statement)) > 0
    )
  ),
  UNIQUE (site_id,id)
);
CREATE INDEX IF NOT EXISTS ix_website_media_site_state
  ON website_cms.media_assets(site_id,state,created_at DESC);

-- Usage references are retained for impact checks before any manual removal.
-- Cross-site references are prevented by compound foreign keys.
CREATE UNIQUE INDEX IF NOT EXISTS ix_website_pages_site_id
  ON website_cms.pages(site_id,id);
CREATE TABLE IF NOT EXISTS website_cms.media_usages (
  site_id uuid NOT NULL,
  asset_id uuid NOT NULL,
  page_id uuid NOT NULL,
  revision_id uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(site_id,asset_id,revision_id),
  FOREIGN KEY (site_id,asset_id)
    REFERENCES website_cms.media_assets(site_id,id) ON DELETE RESTRICT,
  FOREIGN KEY (site_id,page_id)
    REFERENCES website_cms.pages(site_id,id) ON DELETE RESTRICT,
  FOREIGN KEY (page_id,revision_id)
    REFERENCES website_cms.page_revisions(page_id,id) ON DELETE RESTRICT
);
-- Never grant public SELECT on quarantine manifests, claimed checksums or source keys.
-- No blob upload endpoint, public media URL, purge, expiry job or automatic deletion.
COMMIT;
