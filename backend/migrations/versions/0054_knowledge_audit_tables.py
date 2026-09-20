"""Persist the knowledge snapshot and answer-audit models introduced on main.

This is an additive migration: published chunks, sources, and earlier migration
files are not rewritten. Historical answers are not given fabricated evidence.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0054_knowledge_audit_tables"
down_revision = "0053_bot_workflow_builder"
branch_labels = None
depends_on = None


def _identity_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _ownership_constraints() -> list[sa.ForeignKeyConstraint]:
    return [
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
    ]


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "knowledge_snapshots",
        *_identity_columns(),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("manifest", json_type, nullable=False),
        *_ownership_constraints(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "revision", name="uq_knowledge_snapshots_agent_revision"),
    )
    op.create_table(
        "knowledge_answer_audits",
        *_identity_columns(),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("details", json_type, nullable=False),
        *_ownership_constraints(),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["knowledge_snapshots.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for table in ("knowledge_snapshots", "knowledge_answer_audits"):
        for column in ("tenant_id", "workspace_id", "agent_id"):
            op.create_index(f"ix_{table}_{column}", table, [column])
        if op.get_bind().dialect.name == "postgresql":
            # Same transaction-scoped tenant identity as the existing application.
            # Workspace/agent grants must still be checked by the application.
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(
                f'CREATE POLICY tenant_isolation ON "{table}" '
                "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
                "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
            )
            op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO northstar_app')


def downgrade() -> None:
    # Destructive downgrade is explicit; operators must export/retain audit data first.
    op.drop_table("knowledge_answer_audits")
    op.drop_table("knowledge_snapshots")
