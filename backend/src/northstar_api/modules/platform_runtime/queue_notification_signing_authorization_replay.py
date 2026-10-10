"""Durable one-use authorization consumption; no reset or automatic retry."""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import DateTime, String, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base

_ID = re.compile(r"[A-Za-z0-9_-]{16,128}\Z")
_RELEASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,79}\Z")
_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,39}\Z")


class SigningAuthorizationConsumption(Base):
    __tablename__ = "platform_notification_signing_authorizations"

    authorization_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    release_id: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    run_id: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuthorizationConsumption(Protocol):
    async def consume(
        self, *, authorization_id: str, release_id: str, run_id: str,
        now: datetime,
    ) -> None: ...


class CommittedAuthorizationConsumption:
    """Use an independent database session, never the request transaction."""

    def __init__(self, session_factory):
        if not callable(session_factory):
            raise TypeError("independent database session factory required")
        self._factory = session_factory

    async def consume(
        self, *, authorization_id: str, release_id: str, run_id: str,
        now: datetime,
    ) -> None:
        if (
            not isinstance(authorization_id, str)
            or _ID.fullmatch(authorization_id) is None
            or not isinstance(release_id, str)
            or _RELEASE.fullmatch(release_id) is None
            or not isinstance(run_id, str)
            or _RUN.fullmatch(run_id) is None
            or not isinstance(now, datetime) or now.tzinfo is None
        ):
            raise PermissionError("invalid signing authorization consumption")
        try:
            async with self._factory() as session:
                if not isinstance(session, AsyncSession):
                    raise PermissionError("isolated authorization transaction required")
                await session.execute(insert(SigningAuthorizationConsumption).values(
                    authorization_id=authorization_id,
                    release_id=release_id,
                    run_id=run_id,
                    consumed_at=now.astimezone(UTC),
                ))
                await session.commit()
        except Exception as exc:
            # Unknown commit results must never unlock the signing key.
            raise PermissionError("signing authorization already consumed or unavailable") from exc
