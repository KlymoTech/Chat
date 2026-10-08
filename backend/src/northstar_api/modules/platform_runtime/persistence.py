"""Durable control-plane records for desired state and deployment history."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base
from northstar_api.models import MutableJSON, MutableListJSON, TimestampMixin, UUIDPrimaryKeyMixin


class PlatformCapabilityRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Latest desired/observed state for one capability and environment."""

    __tablename__ = "platform_capabilities"
    __table_args__ = (
        UniqueConstraint("environment", "capability_id", name="uq_platform_capabilities_environment_capability"),
        Index("ix_platform_capabilities_environment_health", "environment", "health"),
    )

    environment: Mapped[str] = mapped_column(String(32))
    capability_id: Mapped[str] = mapped_column(String(80))
    provider: Mapped[str] = mapped_column(String(80))
    fallback_provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    desired_state: Mapped[str] = mapped_column(String(16), default="on")
    actual_state: Mapped[str] = mapped_column(String(32), default="unknown")
    health: Mapped[str] = mapped_column(String(32), default="unknown")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)


class PlatformChangeRecord(Base, UUIDPrimaryKeyMixin):
    """Auditable change request; no row implies no infrastructure mutation."""

    __tablename__ = "platform_changes"
    __table_args__ = (
        UniqueConstraint("environment", "idempotency_key", name="uq_platform_changes_environment_idempotency"),
        Index("ix_platform_changes_environment_status_requested", "environment", "status", "requested_at"),
    )

    environment: Mapped[str] = mapped_column(String(32))
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), default="draft")
    action: Mapped[str] = mapped_column(String(16))
    classification: Mapped[str] = mapped_column(String(32))
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    destructive: Mapped[bool] = mapped_column(Boolean, default=False)
    source_revision: Mapped[int] = mapped_column(Integer)
    target_revision: Mapped[int] = mapped_column(Integer)
    source_digest: Mapped[str] = mapped_column(String(64))
    target_digest: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(String(500))
    plan_steps: Mapped[list[str]] = mapped_column(MutableListJSON, default=list)
    blockers: Mapped[list[str]] = mapped_column(MutableListJSON, default=list)
    impact_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rollback_change_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platform_changes.id", ondelete="SET NULL"), nullable=True
    )
    current_spec_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    desired_spec_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)


class PlatformChangeApproval(Base, UUIDPrimaryKeyMixin):
    """Separate approval record enforcing requestor/approver separation."""

    __tablename__ = "platform_change_approvals"
    __table_args__ = (
        UniqueConstraint("change_id", "approver_id", name="uq_platform_change_approvals_change_approver"),
        Index("ix_platform_change_approvals_change_created", "change_id", "created_at"),
    )

    change_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platform_changes.id", ondelete="CASCADE"))
    approver_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decision: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PlatformDeploymentExecution(Base, UUIDPrimaryKeyMixin):
    """Execution evidence reported by an external deployment controller."""

    __tablename__ = "platform_deployment_executions"
    __table_args__ = (
        UniqueConstraint("change_id", "report_key", name="uq_platform_deployment_executions_change_report_key"),
        Index("ix_platform_deployment_executions_change_started", "change_id", "started_at"),
    )

    change_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platform_changes.id", ondelete="CASCADE"))
    report_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pipeline: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    source_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    health_result_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)


class PlatformConfigVersion(Base, UUIDPrimaryKeyMixin):
    """Versioned desired configuration, retained as a rollback target."""

    __tablename__ = "platform_config_versions"
    __table_args__ = (
        UniqueConstraint("environment", "revision", name="uq_platform_config_versions_environment_revision"),
        Index("ix_platform_config_versions_environment_active", "environment", "active"),
        Index(
            "uq_platform_config_versions_one_active_per_environment",
            "environment",
            unique=True,
            postgresql_where=text("active = true"),
            sqlite_where=text("active = 1"),
        ),
    )

    environment: Mapped[str] = mapped_column(String(32))
    revision: Mapped[int] = mapped_column(Integer)
    digest: Mapped[str] = mapped_column(String(64))
    configuration_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


__all__ = [
    "PlatformCapabilityRecord",
    "PlatformChangeApproval",
    "PlatformChangeRecord",
    "PlatformConfigVersion",
    "PlatformDeploymentExecution",
]
