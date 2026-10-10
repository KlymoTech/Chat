-- Blueprint editorial safety: immutable content snapshots and audit history.
-- Additive migration 009. Apply after 001-008 and verify on isolated database.
-- Does not grant any rights and does not create an automatic purge path.
BEGIN;
CREATE OR REPLACE FUNCTION website_cms.guard_revision_snapshot()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'CMS revisions cannot be deleted by the application'
      USING ERRCODE='23514';
  END IF;
  IF ROW(NEW.id,NEW.page_id,NEW.revision_number,NEW.title,
         NEW.description,NEW.blocks,NEW.seo,NEW.actor_id,NEW.created_at)
     IS DISTINCT FROM
     ROW(OLD.id,OLD.page_id,OLD.revision_number,OLD.title,
         OLD.description,OLD.blocks,OLD.seo,OLD.actor_id,OLD.created_at) THEN
    RAISE EXCEPTION 'CMS revision snapshot is immutable'
      USING ERRCODE='23514';
  END IF;
  IF NEW.state = OLD.state THEN RETURN NEW; END IF;
  IF OLD.state = 'draft' AND NEW.state = 'approved' THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Unapproved revision state transition'
    USING ERRCODE='23514';
END
$$;
CREATE TRIGGER website_revision_immutable_guard
 BEFORE UPDATE OR DELETE ON website_cms.page_revisions
 FOR EACH ROW EXECUTE FUNCTION website_cms.guard_revision_snapshot();

CREATE OR REPLACE FUNCTION website_cms.guard_append_only_record()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Protected editorial evidence is append-only'
    USING ERRCODE='23514';
END
$$;
CREATE TRIGGER website_audit_append_only
 BEFORE UPDATE OR DELETE ON website_cms.audit_events
 FOR EACH ROW EXECUTE FUNCTION website_cms.guard_append_only_record();
CREATE TRIGGER website_approval_append_only
 BEFORE UPDATE OR DELETE ON website_cms.revision_approvals
 FOR EACH ROW EXECUTE FUNCTION website_cms.guard_append_only_record();
COMMIT;
