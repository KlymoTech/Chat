-- Safe owner workflow drafts: No auto-enrollment, dispatch, or external effects.
-- Additive after privacy analytics (014). Published execution deliberately absent.
BEGIN;
CREATE TABLE IF NOT EXISTS website_cms.automation_definitions (
  id uuid PRIMARY KEY,
  site_id uuid NOT NULL REFERENCES website_cms.sites(id),
  owner_actor_id uuid NOT NULL,
  title varchar(120) NOT NULL CHECK(length(trim(title))>0),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(site_id,id)
);
CREATE TABLE IF NOT EXISTS website_cms.automation_versions (
  id uuid PRIMARY KEY,
  site_id uuid NOT NULL,
  definition_id uuid NOT NULL,
  version integer NOT NULL CHECK(version BETWEEN 1 AND 2147483647),
  status varchar(16) NOT NULL DEFAULT 'draft' CHECK(status='draft'),
  definition jsonb NOT NULL CHECK(jsonb_typeof(definition)='object'),
  created_by_actor_id uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(site_id,definition_id)
    REFERENCES website_cms.automation_definitions(site_id,id),
  UNIQUE(definition_id,version)
);
CREATE INDEX IF NOT EXISTS ix_website_automation_site
  ON website_cms.automation_definitions(site_id,created_at DESC);
CREATE OR REPLACE FUNCTION website_cms.prevent_automation_version_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'Automation versions are immutable; append another version'
   USING ERRCODE='23514';
END;
$$;
DROP TRIGGER IF EXISTS trg_automation_versions_immutable ON website_cms.automation_versions;
CREATE TRIGGER trg_automation_versions_immutable
BEFORE UPDATE OR DELETE ON website_cms.automation_versions
FOR EACH ROW EXECUTE FUNCTION website_cms.prevent_automation_version_mutation();
-- Never grant these tables to public/visitor DB roles. No worker is installed.
COMMIT;
