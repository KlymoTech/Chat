"""Tenant-independent, exact-ID read access to signed worker evidence.

Certification writes are a separate privileged pipeline responsibility.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .queue_notification_worker_qualification import NotificationQualificationRecord
from .queue_notification_qualification_persistence import NotificationWorkerQualificationRecord


class PostgresNotificationQualificationStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def read(self, qualification_id: str) -> NotificationQualificationRecord | None:
        if not qualification_id or len(qualification_id) > 128:
            return None
        async with self._sessions() as session:
            row = await session.get(NotificationWorkerQualificationRecord, qualification_id)
            if row is None:
                return None
            if not isinstance(row.proof_tokens, list) or not all(
                isinstance(t, str) for t in row.proof_tokens
            ):
                return None
            return NotificationQualificationRecord(
                id=row.id, environment=row.environment,
                source_digest=row.source_digest, target_digest=row.target_digest,
                proof_tokens=tuple(row.proof_tokens),
                approved=row.approved, revoked=row.revoked,
            )
