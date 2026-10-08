"""Persistent queue alert episodes; no external notification side effects."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class QueueAlertEpisode(Base):
    __tablename__ = "platform_queue_alert_episodes"
    __table_args__ = (
        UniqueConstraint("scope_key", "code", name="uq_platform_queue_alert_episode_scope_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    scope_key: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(100))
    severity: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(16))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    occurrences: Mapped[int] = mapped_column(default=1)
