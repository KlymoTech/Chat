-- Editorial approvals are independent, attributable records.
-- Do not mutate prior approvals or revision content.
BEGIN;
CREATE TABLE IF NOT EXISTS website_cms.revision_approvals (
  id uuid PRIMARY KEY,
  site_id uuid NOT NULL REFERENCES website_cms.sites(id),
  page_id uuid NOT NULL,
  revision_id uuid NOT NULL,
  reviewer_id uuid NOT NULL,
  approved_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (revision_id, reviewer_id),
  FOREIGN KEY (page_id, revision_id)
    REFERENCES website_cms.page_revisions(page_id, id)
);
CREATE INDEX IF NOT EXISTS ix_website_approvals_revision
  ON website_cms.revision_approvals(revision_id);
-- No UPDATE / DELETE privileges for the application writer on approval or audit records.
-- Role grants, RLS, session ownership and deployment validation remain required.
COMMIT;
