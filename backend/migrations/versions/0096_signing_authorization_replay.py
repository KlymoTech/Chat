"""Append-only, one-use authorization grants for protected signing."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0096_signing_authorization_replay"
down_revision = "0095_notification_custody_signing_claims"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_notification_signing_authorizations",
        sa.Column("authorization_id", sa.String(128), primary_key=True),
        sa.Column("release_id", sa.String(80), nullable=False, unique=True),
        sa.Column("run_id", sa.String(40), nullable=False, unique=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute(sa.text("""
        CREATE FUNCTION reject_notification_signing_authorization_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Signing authorization consumption is append-only';
        END;
        $$
    """))
    op.execute(sa.text("""
        CREATE TRIGGER signing_authorization_immutable
        BEFORE UPDATE OR DELETE ON platform_notification_signing_authorizations
        FOR EACH ROW EXECUTE FUNCTION
        reject_notification_signing_authorization_mutation()
    """))


def downgrade() -> None:
    if op.get_bind().scalar(sa.text(
        "SELECT COUNT(*) FROM platform_notification_signing_authorizations"
    )):
        raise RuntimeError("Cannot erase consumed signing authorizations")
    op.drop_table("platform_notification_signing_authorizations")
    op.execute(sa.text("DROP FUNCTION reject_notification_signing_authorization_mutation()"))
