-- Additive deployment migration. Existing records require a controlled backfill before
-- this migration is applied to a database containing real submissions.
-- Store a keyed-independent SHA-256 digest of normalized input for retry comparison.
-- Personal fields remain protected in lead_submissions; do not log or expose fingerprints.
BEGIN;
ALTER TABLE website_cms.lead_submissions
 ADD COLUMN IF NOT EXISTS payload_sha256 varchar(64);
-- Backfill from the canonical values already stored. This exactly matches the
-- input normalization in lead-input.ts and lead-payload.ts (newline separated).
CREATE EXTENSION IF NOT EXISTS pgcrypto;
UPDATE website_cms.lead_submissions
 SET payload_sha256 = encode(digest(
   full_name || E'\n' || email || E'\n' || message || E'\ntrue', 'sha256'), 'hex')
 WHERE payload_sha256 IS NULL;
ALTER TABLE website_cms.lead_submissions
 ALTER COLUMN payload_sha256 SET NOT NULL;
ALTER TABLE website_cms.lead_submissions
 ADD CONSTRAINT website_lead_payload_hash_format
 CHECK (payload_sha256 ~ '^[0-9a-f]{64}$');
COMMIT;
