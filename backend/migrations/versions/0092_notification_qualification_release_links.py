"""Add append-only verified release links for notification certification."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0092_notification_qualification_release_links"
down_revision = "0091_notification_qualification_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_notification_qualification_release_links",
        sa.Column("qualification_id", sa.String(128),
                  sa.ForeignKey("platform_notification_worker_qualifications.id", ondelete="RESTRICT"),
                  primary_key=True),
        sa.Column("release_id", sa.String(80), nullable=False),
        sa.Column("run_id", sa.String(40), nullable=False),
        sa.Column("environment", sa.String(32), nullable=False),
        sa.Column("source_commit", sa.String(40), nullable=False),
        sa.Column("image_digest", sa.String(71), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("target_digest", sa.String(64), nullable=False),
        sa.Column("signed_manifest_sha256", sa.String(64), nullable=False),
        sa.Column("manifest_bucket", sa.String(63), nullable=False),
        sa.Column("manifest_key", sa.String(512), nullable=False),
        sa.Column("manifest_version_id", sa.String(255), nullable=False),
        sa.Column("manifest_object_sha256", sa.String(64), nullable=False),
        sa.Column("attestation_bucket", sa.String(63), nullable=False),
        sa.Column("attestation_key", sa.String(512), nullable=False),
        sa.Column("attestation_version_id", sa.String(255), nullable=False),
        sa.Column("attestation_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("release_id", name="uq_notification_qualification_release_id"),
    )

    # Prevent application or privileged job code from silently relinking an
    # already certified release. Administrative correction requires a new
    # qualification ID and explicit incident reconciliation.
    op.execute(sa.text("""
        CREATE FUNCTION reject_notification_qualification_release_link_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'qualification release links are append-only';
        END;
        $$
    """))
    op.execute(sa.text("""
        CREATE TRIGGER notification_qualification_release_links_immutable
        BEFORE UPDATE OR DELETE
        ON platform_notification_qualification_release_links
        FOR EACH ROW EXECUTE FUNCTION
        reject_notification_qualification_release_link_mutation()
    """))


def downgrade() -> None:
    if op.get_bind().scalar(sa.text(
        "SELECT COUNT(*) FROM platform_notification_qualification_release_links"
    )):
        raise RuntimeError("Archive and reconcile release evidence links before downgrade")
    op.drop_table("platform_notification_qualification_release_links")
    op.execute(sa.text("DROP FUNCTION reject_notification_qualification_release_link_mutation()"))
