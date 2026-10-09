"""Durable at-most-once claim before protected custody attestation signing.

A claimed run is deliberately not automatically retryable if signing fails or
the process crashes. Operator reconciliation requires a separately reviewed
release/run rather than reuse of the signed evidence.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0095_notification_custody_signing_claims"
down_revision = "0094_merge_notification_junit_custody_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_notification_custody_signing_claims",
        sa.Column("release_id", sa.String(80), primary_key=True),
        sa.Column("run_id", sa.String(40), nullable=False, unique=True),
        sa.Column("witness_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute(sa.text("""
        CREATE FUNCTION reject_notification_custody_signing_claim_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Custody signing claims are append-only';
        END;
        $$
    """))
    op.execute(sa.text("""
        CREATE TRIGGER notification_custody_signing_claim_immutable
        BEFORE UPDATE OR DELETE ON platform_notification_custody_signing_claims
        FOR EACH ROW EXECUTE FUNCTION
        reject_notification_custody_signing_claim_mutation()
    """))


def downgrade() -> None:
    if op.get_bind().scalar(sa.text(
        "SELECT COUNT(*) FROM platform_notification_custody_signing_claims"
    )):
        raise RuntimeError("Cannot destroy custody signing replay claims")
    op.drop_table("platform_notification_custody_signing_claims")
    op.execute(sa.text("DROP FUNCTION reject_notification_custody_signing_claim_mutation()"))
