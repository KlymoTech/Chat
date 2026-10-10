"""Qualification verifier backed by trusted stored evidence.

The separate certification system writes records; this runtime only reads and
verifies signed, time-bounded proofs. Caller labels cannot bypass verification.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .qualification import verify_qualification_proofs


@dataclass(frozen=True)
class NotificationQualificationRecord:
    id: str
    environment: str
    source_digest: str
    target_digest: str
    proof_tokens: tuple[str, ...]
    approved: bool
    revoked: bool = False


class NotificationQualificationStore(Protocol):
    async def read(self, qualification_id: str) -> NotificationQualificationRecord | None: ...


class PersistedNotificationWorkerQualification:
    REQUIRED = ("notification_worker", "notification_egress", "notification_secrets")

    def __init__(
        self, *,
        store: NotificationQualificationStore,
        qualification_id: str,
        environment: str,
        source_digest: str,
        target_digest: str,
        signing_key: bytes,
    ) -> None:
        self._store = store
        self._id = qualification_id
        self._environment = environment
        self._source = source_digest
        self._target = target_digest
        self._key = signing_key

    async def verify(self) -> bool:
        if not self._id or not self._environment or len(self._key) < 32:
            return False
        try:
            record = await self._store.read(self._id)
            if (
                record is None or record.id != self._id
                or not record.approved or record.revoked
                or record.environment != self._environment
                or record.source_digest != self._source
                or record.target_digest != self._target
                or len(record.proof_tokens) < len(self.REQUIRED)
                or len(record.proof_tokens) > 16
            ):
                return False
            blockers = verify_qualification_proofs(
                record.proof_tokens, required=self.REQUIRED,
                environment=self._environment,
                source_digest=self._source,
                target_digest=self._target,
                signing_key=self._key,
            )
            return not blockers
        except Exception:
            return False
