from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base
from northstar_api.lead_crm.domain import ChannelProvider

JSONType = JSON().with_variant(JSONB, "postgresql")
MutableJSON = MutableDict.as_mutable(JSONType)
MutableListJSON = MutableList.as_mutable(JSON().with_variant(JSONB, "postgresql"))


class ChannelConnection(Base):
    __tablename__ = "channel_connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "public_id", name="uq_channel_connection_public_id"),
        UniqueConstraint("tenant_id", "name", name="uq_channel_connection_name"),
        Index("ix_channel_connections_provider", "tenant_id", "provider", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    public_id: Mapped[str] = mapped_column(String(64), default=lambda: f"chn_{uuid.uuid4().hex}")
    provider: Mapped[str] = mapped_column(String(60), default=ChannelProvider.CUSTOM.value)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(40), default="draft")
    credentials_encrypted: Mapped[bytes | None] = mapped_column(nullable=True)
    credentials_ref: Mapped[str | None] = mapped_column(String(500))
    configuration_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ChannelHealthSnapshot(Base):
    """Safe durable history for scheduled channel connection health checks."""

    __tablename__ = "channel_health_snapshots"
    __table_args__ = (
        Index(
            "ix_channel_health_snapshots_connection_checked",
            "tenant_id",
            "connection_id",
            "checked_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channel_connections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(120))
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class ChannelOutboundDelivery(Base):
    """Durable provider-neutral outbound delivery state.

    Telegram is the first generic-channel runtime using this table. Keeping the
    persistence provider-neutral lets future Instagram/Facebook/Slack outbound
    work reuse the same reliability boundary without changing existing channel
    connection or conversation tables.
    """

    __tablename__ = "channel_outbound_deliveries"
    __table_args__ = (
        UniqueConstraint("provider", "message_id", name="uq_channel_outbound_provider_message"),
        Index(
            "ix_channel_outbound_tenant_provider_status",
            "tenant_id",
            "provider",
            "status",
            "next_dispatch_at",
        ),
        Index("ix_channel_outbound_connection_status", "connection_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("channel_connections.id", ondelete="SET NULL"), index=True
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    recipient_external_id: Mapped[str] = mapped_column(String(180), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="queued", nullable=False)
    provider_message_ids: Mapped[list[str]] = mapped_column(MutableListJSON, default=list, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    dispatch_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_dispatch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ChannelDeliveryAttempt(Base):
    """Append-only, safe operational evidence for one outbound delivery attempt."""

    __tablename__ = "channel_delivery_attempts"
    __table_args__ = (
        UniqueConstraint(
            "delivery_id",
            "phase",
            "attempt_number",
            name="uq_channel_delivery_attempt_number",
        ),
        Index(
            "ix_channel_delivery_attempt_scope",
            "tenant_id",
            "workspace_id",
            "delivery_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    delivery_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channel_outbound_deliveries.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(40), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
