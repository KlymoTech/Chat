"""Irreversible replay claim stored before protected signing key access."""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import DateTime, String, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_RELEASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,79}\Z")
_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,39}\Z")


class CustodySigningClaim(Base):
    __tablename__ = "platform_notification_custody_signing_claims"

    release_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    witness_sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SigningClaimStore(Protocol):
    async def claim(
        self, *, release_id: str, run_id: str, witness_sha256: str,
        now: datetime,
    ) -> None: ...


class CommittedPostgresSigningClaims:
    """One dedicated, isolated DB session per claim; commit precedes signing.

    Session factory MUST provide an independent transaction, not the custody
    readback session or a caller-managed transaction. Duplicate, uncertain,
    unavailable or rolled-back claims refuse signing. Claims are not released.
    """

    def __init__(self, session_factory):
        if not callable(session_factory):
            raise TypeError("independent database session factory required")
        self._factory = session_factory

    async def claim(
        self, *, release_id: str, run_id: str, witness_sha256: str,
        now: datetime,
    ) -> None:
        if (
            not isinstance(release_id, str) or _RELEASE.fullmatch(release_id) is None
            or not isinstance(run_id, str) or _RUN.fullmatch(run_id) is None
            or not isinstance(witness_sha256, str) or _SHA.fullmatch(witness_sha256) is None
            or not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None
        ):
            raise PermissionError("invalid custody signing claim")
        try:
            async with self._factory() as session:
                if not isinstance(session, AsyncSession):
                    raise PermissionError("isolated signing transaction required")
                await session.execute(insert(CustodySigningClaim).values(
                    release_id=release_id, run_id=run_id,
                    witness_sha256=witness_sha256, claimed_at=now.astimezone(UTC),
                ))
                await session.commit()
        except Exception as exc:
            # A lost connection during COMMIT has an unknown outcome. Never
            # retry or unlock a signing key based on an uncertain claim.
            raise PermissionError("custody signing claim unavailable or already used") from exc
