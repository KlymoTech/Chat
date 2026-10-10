"""Transactional append-only audit boundary for deployment-worker actions.

Each machine action writes an intent BEFORE execution and an outcome AFTER
execution. A crash between them leaves a pending attempt; further actions
are refused until independent reconciliation. No credentials or signed
attestation bodies are stored. A PostgreSQL transaction-scoped advisory lock serializes attempts without
requiring UPDATE privilege on approved changes; a unique sequence prevents
racing inserts.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .deployment_machine_identity import DeploymentMachinePrincipal, WorkerAction
from .deployment_worker_audit_persistence import PlatformDeploymentWorkerAudit
from .persistence import PlatformChangeRecord

_ZERO_DIGEST = "0" * 64
_OUTCOMES = frozenset({"accepted", "rejected", "unknown"})


class DeploymentAuditBlocked(RuntimeError):
    """A missing audit boundary or unresolved action prohibits new work."""


@dataclass(frozen=True)
class DeploymentAuditAttempt:
    change_id: UUID
    attempt_id: UUID
    action: WorkerAction
    environment: str
    machine_subject: str
    token_id_hash: str
    step_index: int | None


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def compute_worker_audit_digest(
    *,
    change_id: UUID,
    attempt_id: UUID,
    sequence: int,
    kind: str,
    action: str,
    environment: str,
    machine_subject: str,
    token_id_hash: str,
    step_index: int | None,
    outcome: str | None,
    occurred_at: datetime,
    previous_digest: str,
) -> str:
    payload = {
        "change_id": str(change_id),
        "attempt_id": str(attempt_id),
        "sequence": sequence,
        "kind": kind,
        "action": action,
        "environment": environment,
        "machine_subject": machine_subject,
        "token_id_hash": token_id_hash,
        "step_index": step_index,
        "outcome": outcome,
        "occurred_at": _timestamp(occurred_at),
        "previous_digest": previous_digest,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_worker_audit_chain(events: list[PlatformDeploymentWorkerAudit]) -> bool:
    """Validate exported events; requires ALL events in ascending sequence order."""
    previous = _ZERO_DIGEST
    awaiting: PlatformDeploymentWorkerAudit | None = None
    expected_change_id: UUID | None = None
    recovery_required = False
    for sequence, event in enumerate(events, start=1):
        if expected_change_id is None:
            expected_change_id = event.change_id
        if (
            event.change_id != expected_change_id
            or event.sequence != sequence
            or event.previous_digest != previous
            or recovery_required
        ):
            return False
        if compute_worker_audit_digest(
            change_id=event.change_id,
            attempt_id=event.attempt_id,
            sequence=event.sequence,
            kind=event.kind,
            action=event.action,
            environment=event.environment,
            machine_subject=event.machine_subject,
            token_id_hash=event.token_id_hash,
            step_index=event.step_index,
            outcome=event.outcome,
            occurred_at=event.occurred_at,
            previous_digest=event.previous_digest,
        ) != event.event_digest:
            return False
        if event.kind == "intent" and event.outcome is None and awaiting is None:
            awaiting = event
        elif (
            event.kind == "outcome" and event.outcome in _OUTCOMES
            and awaiting is not None
            and event.attempt_id == awaiting.attempt_id
            and event.action == awaiting.action
            and event.environment == awaiting.environment
            and event.machine_subject == awaiting.machine_subject
            and event.token_id_hash == awaiting.token_id_hash
            and event.step_index == awaiting.step_index
        ):
            recovery_required = event.outcome == "unknown"
            awaiting = None
        else:
            return False
        previous = event.event_digest
    return True


class DeploymentWorkerAuditTrail:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    @staticmethod
    async def _lock_change(
        session: AsyncSession, change_id: UUID, environment: str,
    ) -> None:
        # SELECT FOR UPDATE would require UPDATE permission on an approved
        # change. Use a transaction-scoped lock instead, keeping the worker DB
        # role SELECT-only on the source-of-truth approval record.
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            digest = hashlib.sha256(b"northstar-worker-audit:" + change_id.bytes).digest()
            lock_id = int.from_bytes(digest[:8], byteorder="big", signed=True)
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id},
            )
        matched = await session.scalar(
            select(PlatformChangeRecord.id).where(
                PlatformChangeRecord.id == change_id,
                PlatformChangeRecord.environment == environment,
            )
        )
        if matched is None:
            raise DeploymentAuditBlocked("change is missing or outside worker environment")

    @staticmethod
    async def _tail(session: AsyncSession, change_id: UUID) -> PlatformDeploymentWorkerAudit | None:
        return await session.scalar(
            select(PlatformDeploymentWorkerAudit)
            .where(PlatformDeploymentWorkerAudit.change_id == change_id)
            .order_by(PlatformDeploymentWorkerAudit.sequence.desc()).limit(1)
        )

    @staticmethod
    def _event(
        attempt: DeploymentAuditAttempt, *, sequence: int, kind: str,
        outcome: str | None, previous_digest: str,
    ) -> PlatformDeploymentWorkerAudit:
        occurred = datetime.now(UTC)
        digest = compute_worker_audit_digest(
            change_id=attempt.change_id,
            attempt_id=attempt.attempt_id,
            sequence=sequence,
            kind=kind,
            action=attempt.action,
            environment=attempt.environment,
            machine_subject=attempt.machine_subject,
            token_id_hash=attempt.token_id_hash,
            step_index=attempt.step_index,
            outcome=outcome,
            occurred_at=occurred,
            previous_digest=previous_digest,
        )
        return PlatformDeploymentWorkerAudit(
            id=uuid4(), change_id=attempt.change_id, attempt_id=attempt.attempt_id,
            sequence=sequence, kind=kind, action=attempt.action,
            environment=attempt.environment, machine_subject=attempt.machine_subject,
            token_id_hash=attempt.token_id_hash, step_index=attempt.step_index,
            outcome=outcome, occurred_at=occurred, previous_digest=previous_digest,
            event_digest=digest,
        )

    async def begin(
        self, *, principal: DeploymentMachinePrincipal, change_id: UUID,
        action: WorkerAction, step_index: int | None = None,
    ) -> DeploymentAuditAttempt:
        if step_index is not None and step_index < 0:
            raise ValueError("step index must not be negative")
        attempt = DeploymentAuditAttempt(
            change_id=change_id, attempt_id=uuid4(), action=action,
            environment=principal.environment, machine_subject=principal.subject,
            token_id_hash=hashlib.sha256(principal.token_id.encode()).hexdigest(),
            step_index=step_index,
        )
        async with self.sessions() as session, session.begin():
            await self._lock_change(session, change_id, principal.environment)
            last = await self._tail(session, change_id)
            if last is not None and (last.kind != "outcome" or last.outcome == "unknown"):
                raise DeploymentAuditBlocked("prior machine operation requires reconciliation")
            session.add(self._event(
                attempt, sequence=last.sequence + 1 if last else 1,
                kind="intent", outcome=None,
                previous_digest=last.event_digest if last else _ZERO_DIGEST,
            ))
            await session.flush()
        return attempt

    async def finish(self, attempt: DeploymentAuditAttempt, *, outcome: str) -> None:
        if outcome not in _OUTCOMES:
            raise ValueError("invalid audit outcome")
        async with self.sessions() as session, session.begin():
            await self._lock_change(session, attempt.change_id, attempt.environment)
            last = await self._tail(session, attempt.change_id)
            if (
                last is None or last.kind != "intent"
                or last.attempt_id != attempt.attempt_id
                or last.action != attempt.action
                or last.environment != attempt.environment
                or last.machine_subject != attempt.machine_subject
                or last.token_id_hash != attempt.token_id_hash
                or last.step_index != attempt.step_index
            ):
                raise DeploymentAuditBlocked("operation intent is missing or superseded")
            session.add(self._event(
                attempt, sequence=last.sequence + 1, kind="outcome",
                outcome=outcome, previous_digest=last.event_digest,
            ))
            await session.flush()
