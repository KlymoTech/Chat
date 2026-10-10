"""Append-only DB custody of signed Jenkins witness and original S3 versions.

The database record is the independent source of receipts for downstream
readback, not a substitute for signature, S3 Object Lock or IAM validation.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class NotificationJenkinsJunitCustodyRecord(Base):
    __tablename__ = "platform_notification_jenkins_junit_custody"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_notification_jenkins_junit_custody_run"),
    )

    release_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(40), nullable=False)
    branch: Mapped[str] = mapped_column(String(200), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    source_commit: Mapped[str] = mapped_column(String(40), nullable=False)
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    target_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    witness_token: Mapped[str] = mapped_column(Text, nullable=False)
    witness_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    index_bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    index_key: Mapped[str] = mapped_column(String(512), nullable=False)
    index_version_id: Mapped[str] = mapped_column(String(255), nullable=False)
    index_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    suite_receipts: Mapped[dict[str, dict[str, str]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
