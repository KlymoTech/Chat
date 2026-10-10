"""Append-only, chain-linked deployment worker operation audit.

No historical execution events are fabricated. A deployment-specific database
role must have INSERT/SELECT only, with no UPDATE/DELETE permission.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0087_platform_deployment_worker_audit"
down_revision = "0086_platform_deployment_step_journal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_deployment_worker_audit",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("change_id", sa.Uuid(), sa.ForeignKey("platform_changes.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("environment", sa.String(32), nullable=False),
        sa.Column("machine_subject", sa.String(160), nullable=False),
        sa.Column("token_id_hash", sa.String(64), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(16), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_digest", sa.String(64), nullable=False),
        sa.Column("event_digest", sa.String(64), nullable=False),
        sa.UniqueConstraint("change_id", "sequence",
                            name="uq_platform_worker_audit_change_sequence"),
        sa.UniqueConstraint("attempt_id", "kind",
                            name="uq_platform_worker_audit_attempt_kind"),
    )
    op.create_index("ix_platform_worker_audit_change_time",
                    "platform_deployment_worker_audit", ["change_id", "occurred_at"])
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION platform_worker_audit_append_only() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'deployment worker audit is append-only';
            END;
            $$;
        """)
        op.execute("""
            CREATE TRIGGER platform_worker_audit_immutable
            BEFORE UPDATE OR DELETE ON platform_deployment_worker_audit
            FOR EACH ROW EXECUTE FUNCTION platform_worker_audit_append_only();
        """)


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM platform_deployment_worker_audit")):
        raise RuntimeError("Export and reconcile deployment worker audit before downgrade")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER platform_worker_audit_immutable ON platform_deployment_worker_audit")
        op.execute("DROP FUNCTION platform_worker_audit_append_only()")
    op.drop_index("ix_platform_worker_audit_change_time",
                  table_name="platform_deployment_worker_audit")
    op.drop_table("platform_deployment_worker_audit")
