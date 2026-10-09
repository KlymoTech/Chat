"""Read-only certification evidence persisted for notification worker startup."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class NotificationWorkerQualificationRecord(Base):
    __tablename__ = "platform_notification_worker_qualifications"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    target_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    proof_tokens: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
