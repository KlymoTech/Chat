-- Additive lead capture foundation. Apply only to approved isolated PostgreSQL.
-- Do not schedule deletion, and do not treat this as a complete retention/DSAR policy.
BEGIN;
CREATE TABLE IF NOT EXISTS website_cms.lead_submissions (
  id uuid PRIMARY KEY,
  site_id uuid NOT NULL REFERENCES website_cms.sites(id),
  idempotency_key uuid NOT NULL,
  full_name varchar(160) NOT NULL,
  email varchar(254) NOT NULL,
  message varchar(4000) NOT NULL,
  privacy_acknowledged boolean NOT NULL CHECK (privacy_acknowledged),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(site_id, idempotency_key),
  CHECK(length(trim(full_name)) BETWEEN 1 AND 160),
  CHECK(length(trim(message)) BETWEEN 1 AND 4000)
);
CREATE INDEX IF NOT EXISTS ix_website_leads_site_created
  ON website_cms.lead_submissions(site_id, created_at DESC);
-- The existing website_cms.outbox records delivery intents in the same transaction.
-- Provision a separate INSERT/SELECT-limited ingestion role and explicit RLS
--/tenant isolation before enabling the endpoint. Never expose this table publicly.
COMMIT;
