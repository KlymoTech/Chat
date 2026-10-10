-- Additive durable INTERNAL automation state. No outbound provider dispatch.
-- Depends on 015_automation_drafts. Activations must be independently reviewed
-- before any real enrollment is permitted; this migration does not enable them.
BEGIN;
ALTER TABLE website_cms.automation_versions
 ADD CONSTRAINT automation_site_version_unique
 UNIQUE(site_id,definition_id,version);
CREATE TABLE IF NOT EXISTS website_cms.automation_internal_runs (
 id uuid PRIMARY KEY,
 site_id uuid NOT NULL,
 definition_id uuid NOT NULL,
 version integer NOT NULL,
 subject_type varchar(16) NOT NULL CHECK(subject_type IN ('synthetic','lead')),
 subject_id uuid NOT NULL,
 trigger_event_id uuid NOT NULL,
 context jsonb NOT NULL CHECK(jsonb_typeof(context)='object'
   AND octet_length(context::text)<=1024),
 current_node_id varchar(40) NOT NULL CHECK(current_node_id ~ '^[a-z][a-z0-9_-]{0,39}$'),
 status varchar(16) NOT NULL DEFAULT 'enrolled' CHECK(
  status IN('enrolled','running','waiting','completed','cancelled','failed')),
 due_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL,
 processed_steps integer NOT NULL DEFAULT 0 CHECK(processed_steps BETWEEN 0 AND 60),
 claimed_by uuid,
 claimed_until timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),
 finished_at timestamptz,
 last_error_code varchar(80),
 FOREIGN KEY(site_id,definition_id,version)
  REFERENCES website_cms.automation_versions(site_id,definition_id,version),
 UNIQUE(site_id,definition_id,version,subject_id,trigger_event_id),
 UNIQUE(site_id,id),
 CHECK(expires_at>created_at AND expires_at<=created_at+interval '14 days'),
 CHECK ((claimed_by IS NULL AND claimed_until IS NULL)
    OR (claimed_by IS NOT NULL AND claimed_until IS NOT NULL)),
 CHECK ((status IN ('completed','cancelled','failed'))=(finished_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS ix_website_automation_due
 ON website_cms.automation_internal_runs(due_at,claimed_until)
 WHERE status IN('enrolled','running','waiting');
CREATE TABLE IF NOT EXISTS website_cms.automation_run_steps (
 id uuid PRIMARY KEY,
 site_id uuid NOT NULL,
 run_id uuid NOT NULL,
 FOREIGN KEY(site_id,run_id) REFERENCES website_cms.automation_internal_runs(site_id,id),
 step_number integer NOT NULL CHECK(step_number BETWEEN 1 AND 60),
 node_id varchar(40) NOT NULL,
 result varchar(16) NOT NULL CHECK(result IN('advanced','waiting','completed','blocked')),
 recorded_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(run_id,step_number)
);
CREATE TABLE IF NOT EXISTS website_cms.automation_internal_tasks (
 id uuid PRIMARY KEY,
 site_id uuid NOT NULL,
 run_id uuid NOT NULL,
 FOREIGN KEY(site_id,run_id) REFERENCES website_cms.automation_internal_runs(site_id,id),
 node_id varchar(40) NOT NULL,
 action varchar(32) NOT NULL CHECK(action IN('review_lead','notify_owner')),
 state varchar(16) NOT NULL DEFAULT 'pending' CHECK(state IN('pending','done','cancelled')),
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(run_id,node_id)
);
-- Do not grant these tables to a public or CRM role. No triggers automatically
-- enroll leads and no worker sends email, WhatsApp, SMS or provider requests.
COMMIT;
