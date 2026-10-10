"""Append-only custody of immutable Jenkins witness and JUnit version receipts."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0093_notification_jenkins_junit_custody"
down_revision = "0092_notification_qualification_release_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_notification_jenkins_junit_custody",
        sa.Column("release_id", sa.String(80), primary_key=True),
        sa.Column("run_id", sa.String(40), nullable=False),
        sa.Column("branch", sa.String(200), nullable=False),
        sa.Column("environment", sa.String(32), nullable=False),
        sa.Column("source_commit", sa.String(40), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("target_digest", sa.String(64), nullable=False),
        sa.Column("witness_token", sa.Text(), nullable=False),
        sa.Column("witness_sha256", sa.String(64), nullable=False),
        sa.Column("index_bucket", sa.String(63), nullable=False),
        sa.Column("index_key", sa.String(512), nullable=False),
        sa.Column("index_version_id", sa.String(255), nullable=False),
        sa.Column("index_sha256", sa.String(64), nullable=False),
        sa.Column("suite_receipts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", name="uq_notification_jenkins_junit_custody_run"),
    )
    # These records are never mutable after first acceptance. A revision
    # needs a newly signed witness and independently approved release/run.
    op.execute(sa.text("""
        CREATE FUNCTION reject_notification_jenkins_junit_custody_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Jenkins JUnit evidence custody is append-only';
        END;
        $$
    """))
    op.execute(sa.text("""
        CREATE TRIGGER notification_jenkins_junit_custody_immutable
        BEFORE UPDATE OR DELETE
        ON platform_notification_jenkins_junit_custody
        FOR EACH ROW EXECUTE FUNCTION
        reject_notification_jenkins_junit_custody_mutation()
    """))


def downgrade() -> None:
    if op.get_bind().scalar(sa.text(
        "SELECT COUNT(*) FROM platform_notification_jenkins_junit_custody"
    )):
        raise RuntimeError("Reconcile archived Jenkins JUnit custody before downgrade")
    op.drop_table("platform_notification_jenkins_junit_custody")
    op.execute(sa.text("DROP FUNCTION reject_notification_jenkins_junit_custody_mutation()"))
