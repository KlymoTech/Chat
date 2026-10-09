"""Append-only link between a certified release and worker governance evidence.

Only independently verified S3 receipts may be persisted here. Database
uniqueness fences reusing qualification or release IDs with different proofs.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class NotificationQualificationReleaseLink(Base):
    __tablename__ = "platform_notification_qualification_release_links"
    __table_args__ = (
        UniqueConstraint("release_id", name="uq_notification_qualification_release_id"),
    )

    qualification_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("platform_notification_worker_qualifications.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    release_id: Mapped[str] = mapped_column(String(80), nullable=False)
    run_id: Mapped[str] = mapped_column(String(40), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    source_commit: Mapped[str] = mapped_column(String(40), nullable=False)
    image_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    target_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    signed_manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    manifest_key: Mapped[str] = mapped_column(String(512), nullable=False)
    manifest_version_id: Mapped[str] = mapped_column(String(255), nullable=False)
    manifest_object_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    attestation_bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    attestation_key: Mapped[str] = mapped_column(String(512), nullable=False)
    attestation_version_id: Mapped[str] = mapped_column(String(255), nullable=False)
    attestation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
