-- Website blueprint: retry ledger for at-least-once lead delivery.
-- Apply after 001-006, with approved backup and role/RLS checks.
BEGIN;
ALTER TABLE website_cms.outbox
 ADD COLUMN IF NOT EXISTS next_attempt_at timestamptz NOT NULL DEFAULT now(),
 ADD COLUMN IF NOT EXISTS last_error_code varchar(80);
CREATE INDEX IF NOT EXISTS ix_website_outbox_lead_due
 ON website_cms.outbox(next_attempt_at,created_at)
 WHERE delivered_at IS NULL AND event_type='lead.accepted';
-- No data removal and no expiration for retained source or outbox events.
COMMIT;
