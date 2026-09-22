"""Persist platform capability state and reviewable change lifecycle records."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0067_platform_control_plane_state"
down_revision = "0066_workspace_notification_settings_records"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "platform_capabilities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("capability_id", sa.String(length=80), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("fallback_provider", sa.String(length=80), nullable=True),
        sa.Column("desired_state", sa.String(length=16), nullable=False, server_default="on"),
        sa.Column("actual_state", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("health", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("metadata_json", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("environment", "capability_id", name="uq_platform_capabilities_environment_capability"),
    )
    op.create_index(
        "ix_platform_capabilities_environment_health",
        "platform_capabilities",
        ["environment", "health"],
    )

    op.create_table(
        "platform_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("destructive", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("target_revision", sa.Integer(), nullable=False),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column("target_digest", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("plan_steps", JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("blockers", JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("impact_json", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rollback_change_id", sa.Uuid(), nullable=True),
        sa.Column("current_spec_json", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("desired_spec_json", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["rollback_change_id"], ["platform_changes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("environment", "idempotency_key", name="uq_platform_changes_environment_idempotency"),
    )
    op.create_index(
        "ix_platform_changes_environment_status_requested",
        "platform_changes",
        ["environment", "status", "requested_at"],
    )

    op.create_table(
        "platform_change_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("change_id", sa.Uuid(), nullable=False),
        sa.Column("approver_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["change_id"], ["platform_changes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approver_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("change_id", "approver_id", name="uq_platform_change_approvals_change_approver"),
    )
    op.create_index(
        "ix_platform_change_approvals_change_created",
        "platform_change_approvals",
        ["change_id", "created_at"],
    )

    op.create_table(
        "platform_deployment_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("change_id", sa.Uuid(), nullable=False),
        sa.Column("pipeline", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("health_result_json", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["change_id"], ["platform_changes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_platform_deployment_executions_change_started",
        "platform_deployment_executions",
        ["change_id", "started_at"],
    )

    op.create_table(
        "platform_config_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("configuration_json", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("environment", "revision", name="uq_platform_config_versions_environment_revision"),
    )
    op.create_index(
        "ix_platform_config_versions_environment_active",
        "platform_config_versions",
        ["environment", "active"],
    )


def downgrade() -> None:
    op.drop_table("platform_config_versions")
    op.drop_index("ix_platform_deployment_executions_change_started", table_name="platform_deployment_executions")
    op.drop_table("platform_deployment_executions")
    op.drop_index("ix_platform_change_approvals_change_created", table_name="platform_change_approvals")
    op.drop_table("platform_change_approvals")
    op.drop_index("ix_platform_changes_environment_status_requested", table_name="platform_changes")
    op.drop_table("platform_changes")
    op.drop_index("ix_platform_capabilities_environment_health", table_name="platform_capabilities")
    op.drop_table("platform_capabilities")
