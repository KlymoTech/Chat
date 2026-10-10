-- Additive inspection evidence for privately quarantined images.
-- Depends on 011_media_quarantine.sql; no public grants or automatic approval.
BEGIN;
ALTER TABLE website_cms.media_assets
  ADD COLUMN IF NOT EXISTS sanitized_key text,
  ADD COLUMN IF NOT EXISTS sanitized_sha256 char(64),
  ADD COLUMN IF NOT EXISTS sanitized_byte_size bigint,
  ADD COLUMN IF NOT EXISTS scan_engine varchar(80),
  ADD COLUMN IF NOT EXISTS inspected_at timestamptz;
ALTER TABLE website_cms.media_assets
  ADD CONSTRAINT website_media_derivative_evidence_complete CHECK (
    (sanitized_key IS NULL AND sanitized_sha256 IS NULL
       AND sanitized_byte_size IS NULL AND scan_engine IS NULL AND inspected_at IS NULL)
    OR
    (sanitized_key IS NOT NULL AND sanitized_key LIKE 'processed/%'
       AND sanitized_sha256 ~ '^[0-9a-f]{64}$'
       AND sanitized_byte_size BETWEEN 1 AND 10485760
       AND scan_engine IS NOT NULL AND length(trim(scan_engine))>0
       AND inspected_at IS NOT NULL
       AND scanned_at IS NOT NULL
       AND scanner_receipt_sha256 IS NOT NULL)
  );
ALTER TABLE website_cms.media_assets
  ADD CONSTRAINT website_media_approval_requires_processed_image CHECK (
    state <> 'approved' OR (
       sanitized_key IS NOT NULL AND sanitized_sha256 IS NOT NULL
       AND sanitized_byte_size IS NOT NULL AND scan_engine IS NOT NULL
       AND inspected_at IS NOT NULL
       AND reviewed_by_actor_id <> created_by_actor_id
    )
  );
-- No DELETE, TTL, public published media view, or automatic approval.
COMMIT;
