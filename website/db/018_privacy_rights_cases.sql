-- Privacy rights case tracking only. No visitor identification or automatic deletion.
-- A verified case can be tracked without placing applicant PII in audit tables.
-- This migration does NOT create deletion workers or bypass manual hold review.
BEGIN;
CREATE TABLE IF NOT EXISTS website_cms.privacy_rights_cases (
 id uuid PRIMARY KEY,
 site_id uuid NOT NULL REFERENCES website_cms.sites(id),
 request_kind varchar(16) NOT NULL CHECK(request_kind IN
   ('access','correction','erasure','objection','restriction')),
 status varchar(24) NOT NULL DEFAULT 'intake' CHECK(status IN
   ('intake','pending_verification','verified','under_review','legal_hold',
    'approved','denied','in_execution','fulfilled')),
 created_by_actor_id uuid NOT NULL,
 revision integer NOT NULL DEFAULT 1 CHECK(revision>0),
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 -- A jurisdiction-specific due date requires human approval, not a guessed SLA.
 review_due_at timestamptz,
 UNIQUE(site_id,id)
);
CREATE INDEX IF NOT EXISTS ix_website_privacy_rights_site_status
 ON website_cms.privacy_rights_cases(site_id,status,created_at DESC);
CREATE TABLE IF NOT EXISTS website_cms.privacy_rights_history (
 id uuid PRIMARY KEY,
 site_id uuid NOT NULL,
 case_id uuid NOT NULL,
 revision integer NOT NULL CHECK(revision>=1),
 actor_id uuid NOT NULL,
 from_status varchar(24),
 to_status varchar(24) NOT NULL,
 evidence_ref uuid,
 reason_code varchar(40) NOT NULL CHECK(reason_code IN (
  'intake_recorded','identity_requested','identity_confirmed',
  'review_requested','legal_review_required','lawful_hold_confirmed',
  'hold_released','scope_approved','policy_exception','execution_started',
  'execution_evidence_reviewed')),
 recorded_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(site_id,case_id) REFERENCES website_cms.privacy_rights_cases(site_id,id),
 UNIQUE(case_id,revision),
 CHECK(from_status IS DISTINCT FROM to_status),
 CHECK (to_status NOT IN ('verified','denied','fulfilled') OR evidence_ref IS NOT NULL)
);
CREATE OR REPLACE FUNCTION website_cms.privacy_rights_history_immutable()
 RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'Rights case history cannot be edited or deleted'
 USING ERRCODE='23514';
END $$;
DROP TRIGGER IF EXISTS trg_website_rights_immutable
 ON website_cms.privacy_rights_history;
CREATE TRIGGER trg_website_rights_immutable
 BEFORE UPDATE OR DELETE ON website_cms.privacy_rights_history
 FOR EACH ROW EXECUTE FUNCTION website_cms.privacy_rights_history_immutable();
-- Explicit DBA grants and tenant isolation proof required before activating.
-- Neither table stores requesters' email, IP, address, uploaded documents,
-- scanned IDs, sensitive dispute details or message text.
COMMIT;
