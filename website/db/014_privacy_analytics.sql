-- Additive, privacy-first collection for optional purposes. Depends on migrations 001-013.
-- These tables contain no visitor IP, user-agent, raw URL query, email, phone or form values.
-- No external advertising/analytics destination is activated by this migration.
BEGIN;
CREATE TABLE IF NOT EXISTS website_cms.consent_choices (
 id uuid PRIMARY KEY,
 site_id uuid NOT NULL REFERENCES website_cms.sites(id),
 policy_version varchar(32) NOT NULL CHECK (policy_version ~ '^[a-z0-9._-]{1,32}$'),
 analytics_allowed boolean NOT NULL DEFAULT false,
 marketing_allowed boolean NOT NULL DEFAULT false,
 selected_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL,
 withdrawn_at timestamptz,
 CHECK (expires_at > selected_at AND expires_at <= selected_at + interval '30 days'),
 UNIQUE(site_id,id)
);
CREATE INDEX IF NOT EXISTS ix_website_consent_site_current
 ON website_cms.consent_choices(site_id,expires_at) WHERE withdrawn_at IS NULL;

CREATE TABLE IF NOT EXISTS website_cms.analytics_events (
 id uuid PRIMARY KEY,
 site_id uuid NOT NULL,
 consent_id uuid NOT NULL,
 event_name varchar(32) NOT NULL CHECK (event_name IN (
   'content_view','cta_click','navigation_click','faq_open','form_start'
 )),
 action_key varchar(80) NOT NULL CHECK (action_key ~ '^[a-z0-9_-]{1,80}$'),
 route_path varchar(512) NOT NULL CHECK (
   route_path ~ '^/(?:$|services$|about$|contact$|resources$|blog$|content/[a-z0-9]+(-[a-z0-9]+)*$)'
 ),
 received_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(site_id,consent_id) REFERENCES website_cms.consent_choices(site_id,id)
);
CREATE INDEX IF NOT EXISTS ix_website_analytics_site_daily
 ON website_cms.analytics_events(site_id,received_at,event_name);
CREATE TABLE IF NOT EXISTS website_cms.analytics_rate_windows (
 site_id uuid NOT NULL,
 consent_id uuid NOT NULL,
 window_start timestamptz NOT NULL,
 accepted_count integer NOT NULL CHECK (accepted_count BETWEEN 1 AND 30),
 PRIMARY KEY(site_id,consent_id,window_start),
 FOREIGN KEY(site_id,consent_id) REFERENCES website_cms.consent_choices(site_id,id)
);
-- Privacy retention/DSAR erasure must be implemented and operator-reviewed
-- before enabling. No automatic deletion of CMS, blog, audits or content.
COMMIT;
