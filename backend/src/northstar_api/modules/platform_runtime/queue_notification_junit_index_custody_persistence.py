"""Append-only custody of original Jenkins JUnit evidence-index receipts.

This model records what a separate protected publisher confirmed, not an
authorization to sign, approve, or deploy. The database migration prevents
updates/deletion and fences reuse of a release or run with different proofs.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class NotificationJunitIndexCustody(Base):
    __tablename__ = "platform_notification_junit_index_custody"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_notification_junit_custody_run"),
    )

    release_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(40), nullable=False)
    branch: Mapped[str] = mapped_column(String(200), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    source_commit: Mapped[str] = mapped_column(String(40), nullable=False)
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    target_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    witness_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    index_bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    index_key: Mapped[str] = mapped_column(String(512), nullable=False)
    index_version_id: Mapped[str] = mapped_column(String(255), nullable=False)
    index_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    worker_key: Mapped[str] = mapped_column(String(512), nullable=False)
    worker_version_id: Mapped[str] = mapped_column(String(255), nullable=False)
    worker_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    egress_bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    egress_key: Mapped[str] = mapped_column(String(512), nullable=False)
    egress_version_id: Mapped[str] = mapped_column(String(255), nullable=False)
    egress_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    secrets_bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    secrets_key: Mapped[str] = mapped_column(String(512), nullable=False)
    secrets_version_id: Mapped[str] = mapped_column(String(255), nullable=False)
    secrets_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
