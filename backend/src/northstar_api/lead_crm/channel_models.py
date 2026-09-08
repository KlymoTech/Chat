from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base
from northstar_api.lead_crm.domain import ChannelProvider

JSONType = JSON().with_variant(JSONB, "postgresql")
MutableJSON = MutableDict.as_mutable(JSONType)


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
