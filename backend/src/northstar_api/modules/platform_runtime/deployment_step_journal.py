"""Fenced and independently verified deployment step journal.

Only records *intent* and *evidence*; it does not call AWS. An unknown step
cannot be retried or advanced without a separate operator reconciliation flow.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .approval_integrity import persisted_change_integrity_blockers
from .contracts import PlatformSpec
from .control_plane import build_change_plan
from .deployment_lease_persistence import PlatformDeploymentLease
from .deployment_leases import DeploymentClaim
from .deployment_step_attestations import verify_step_attestation
from .deployment_step_persistence import PlatformDeploymentStep
from .persistence import PlatformChangeRecord

_ALLOWED_EXECUTION_STATES = frozenset({
    "approved", "provisioning", "deploying", "verifying", "stabilizing",
})


@dataclass(frozen=True)
class DeploymentStepClaim:
    change_id: UUID
    step_index: int
    step_name: str
    lease_token: UUID


class DeploymentStepJournal:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def _owned_plan(self, session: AsyncSession, claim: DeploymentClaim, now: datetime):
        """Serialize by the lease row and validate the exact approved plan."""
        lease = await session.scalar(
            select(PlatformDeploymentLease).where(
                PlatformDeploymentLease.change_id == claim.change_id,
            ).with_for_update()
        )
        if (
            lease is None
            or lease.status != "leased"
            or lease.owner != claim.owner
            or lease.lease_token != claim.lease_token
            or lease.lease_expires_at is None
            or lease.lease_expires_at <= now
        ):
            return None
        change = await session.get(PlatformChangeRecord, claim.change_id)
        if (
            change is None
            or change.status not in _ALLOWED_EXECUTION_STATES
            or change.approved_by is None
            or change.requested_by == change.approved_by
            or change.environment != lease.environment
            or change.source_digest != lease.source_digest
            or change.target_digest != lease.target_digest
        ):
            return None
        if persisted_change_integrity_blockers(
            current_json=change.current_spec_json,
            desired_json=change.desired_spec_json,
            environment=change.environment,
            source_revision=change.source_revision,
            target_revision=change.target_revision,
            source_digest=change.source_digest,
            target_digest=change.target_digest,
            action=change.action,
            classification=change.classification,
        ):
            return None
        plan = build_change_plan(
            PlatformSpec.model_validate(change.current_spec_json),
            PlatformSpec.model_validate(change.desired_spec_json),
        )
        if (
            plan.action in {"noop", "reject"}
            or tuple(change.plan_steps) != plan.steps
            or not plan.steps
        ):
            return None
        return change, plan

    async def begin_step(self, claim: DeploymentClaim, index: int) -> DeploymentStepClaim | None:
        """Start strictly the next step. Existing/ambiguous steps never rerun."""
        now = datetime.now(UTC)
        async with self.sessions() as session, session.begin():
            state = await self._owned_plan(session, claim, now)
            if state is None:
                return None
            _, plan = state
            if not 0 <= index < len(plan.steps):
                return None
            if index:
                previous = await session.get(PlatformDeploymentStep, (claim.change_id, index - 1))
                if previous is None or previous.status != "verified":
                    return None
            if await session.get(PlatformDeploymentStep, (claim.change_id, index)) is not None:
                return None
            step = DeploymentStepClaim(claim.change_id, index, plan.steps[index], claim.lease_token)
            session.add(PlatformDeploymentStep(
                change_id=claim.change_id,
                step_index=index,
                step_name=step.step_name,
                status="running",
                lease_token=claim.lease_token,
                started_at=now,
            ))
            return step

    async def verify_step(
        self,
        claim: DeploymentClaim,
        index: int,
        *,
        signed_attestation: str,
        verifier_public_key_pem: bytes,
    ) -> bool:
        """Complete only with a fresh independent Ed25519 step attestation."""
        now = datetime.now(UTC)
        async with self.sessions() as session, session.begin():
            state = await self._owned_plan(session, claim, now)
            if state is None:
                return False
            change, plan = state
            if not 0 <= index < len(plan.steps):
                return False
            step = await session.get(PlatformDeploymentStep, (claim.change_id, index))
            if (
                step is None or step.status != "running"
                or step.lease_token != claim.lease_token
                or step.step_name != plan.steps[index]
            ):
                return False
            proof = verify_step_attestation(
                signed_attestation,
                public_key_pem=verifier_public_key_pem,
                change_id=claim.change_id,
                lease_token=claim.lease_token,
                environment=change.environment,
                step_index=index,
                step_name=step.step_name,
                source_digest=change.source_digest,
                target_digest=change.target_digest,
                now=now,
            )
            if proof is None:
                return False
            step.status = "verified"
            step.evidence_digest = proof.evidence_digest
            step.verifier_run_id = proof.verifier_run_id
            step.finished_at = now
            return True

    async def mark_unknown(self, claim: DeploymentClaim, index: int, *, reason: str) -> bool:
        """Freeze an ambiguous external effect; never automatically retry it."""
        if len(reason.strip()) < 5 or len(reason) > 500:
            raise ValueError("a meaningful reconciliation reason is required")
        now = datetime.now(UTC)
        async with self.sessions() as session, session.begin():
            if await self._owned_plan(session, claim, now) is None:
                return False
            step = await session.get(PlatformDeploymentStep, (claim.change_id, index))
            if step is None or step.status != "running" or step.lease_token != claim.lease_token:
                return False
            step.status = "unknown"
            step.unknown_reason = reason
            step.finished_at = now
            return True
