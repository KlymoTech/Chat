-- Additive durable abuse backstop for newly accepted enquiries.
-- Apply AFTER 001-007 in an approved, backed-up isolated PostgreSQL database.
-- Rates are site-scoped; raw email, IP and message are never stored here.
-- This is NOT comprehensive bot protection or a production privacy/retention policy.
BEGIN;
CREATE TABLE IF NOT EXISTS website_cms.lead_rate_windows (
  site_id uuid NOT NULL REFERENCES website_cms.sites(id),
  window_start timestamptz NOT NULL,
  dimension varchar(16) NOT NULL CHECK (dimension IN ('site','contact')),
  subject_hash char(64) NOT NULL CHECK (subject_hash ~ '^[0-9a-f]{64}$'),
  accepted_count integer NOT NULL CHECK (accepted_count BETWEEN 1 AND 2147483647),
  PRIMARY KEY(site_id,window_start,dimension,subject_hash)
);
CREATE INDEX IF NOT EXISTS ix_website_lead_rate_window
  ON website_cms.lead_rate_windows(window_start);
-- Runtime ingestion role requires INSERT and restricted UPDATE/SELECT here only.
-- Do not grant DELETE/TRUNCATE on leads, source content, audit or outbox.
-- Agree a privacy-reviewed retention/cleanup schedule for these derived counters
-- before enabling; this migration creates NO automatic deletion task.
COMMIT;
