-- Additive, isolated schema foundation for Website Blueprint v1.3.
-- Apply manually to an approved PostgreSQL database; NOT connected to Chat migrations.
-- No automatic deletion/purging. Admin write APIs must enforce RBAC and auditing first.
BEGIN;
CREATE SCHEMA IF NOT EXISTS website_cms;
CREATE TABLE IF NOT EXISTS website_cms.sites (
  id uuid PRIMARY KEY, slug text NOT NULL UNIQUE,
  name text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS website_cms.pages (
  id uuid PRIMARY KEY, site_id uuid NOT NULL REFERENCES website_cms.sites(id),
  locale text NOT NULL DEFAULT 'en', path text NOT NULL,
  current_published_revision_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (site_id, locale, path),
  CONSTRAINT valid_page_path CHECK (path LIKE '/%' AND path NOT LIKE '%?%' AND path NOT LIKE '%#%')
);
CREATE TABLE IF NOT EXISTS website_cms.page_revisions (
  id uuid PRIMARY KEY, page_id uuid NOT NULL REFERENCES website_cms.pages(id),
  revision_number integer NOT NULL CHECK (revision_number > 0),
  state text NOT NULL CHECK (state IN ('draft','review','approved','published','archived')),
  title text NOT NULL, description text NOT NULL DEFAULT '',
  blocks jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(blocks) = 'array'),
  seo jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(seo) = 'object'),
  actor_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(page_id, revision_number), UNIQUE(page_id, id)
);
ALTER TABLE website_cms.pages ADD CONSTRAINT published_revision_belongs_to_page
  FOREIGN KEY(id, current_published_revision_id)
  REFERENCES website_cms.page_revisions(page_id, id)
  DEFERRABLE INITIALLY DEFERRED;
CREATE TABLE IF NOT EXISTS website_cms.audit_events (
  id uuid PRIMARY KEY, site_id uuid NOT NULL REFERENCES website_cms.sites(id),
  actor_id uuid NOT NULL, action text NOT NULL, target_id uuid NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS website_cms.outbox (
  id uuid PRIMARY KEY, site_id uuid NOT NULL REFERENCES website_cms.sites(id),
  event_type text NOT NULL, payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  delivered_at timestamptz, attempts integer NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_website_cms_outbox_pending ON website_cms.outbox(created_at) WHERE delivered_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_website_cms_pages_site ON website_cms.pages(site_id, locale);
-- No DELETE or TRUNCATE grants should be given to the runtime role.
COMMIT;
