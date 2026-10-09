"""Durable, fenced worker ownership for independently approved deployment changes.

A lease is a coordination primitive, NOT AWS authorization. The worker must
also verify trusted qualification evidence, the signed plan, current incident
guards and appropriate machine credentials before each external side effect.

Expired leases are deliberately NOT reclaimable automatically: an ambiguous
infrastructure mutation requires reconciliation before any retry.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .deployment_lease_persistence import PlatformDeploymentLease
from .persistence import PlatformChangeRecord, PlatformConfigVersion


@dataclass(frozen=True)
class DeploymentClaim:
    change_id: UUID
    lease_token: UUID
    owner: str
    expires_at: datetime
    environment: str | None = None


class DeploymentLeaseService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], *, lease_seconds: int = 90) -> None:
        if not 10 <= lease_seconds <= 3600:
            raise ValueError("deployment lease must be between 10 and 3600 seconds")
        self.sessions = sessions
        self.lease_seconds = lease_seconds

    async def claim(
        self, change_id: UUID, *, owner: str, expected_environment: str | None = None,
    ) -> DeploymentClaim | None:
        """Atomic compare-and-swap; no duplicate workers for the same change."""
        if not owner or len(owner) > 160:
            raise ValueError("valid deployment worker identity required")
        now = datetime.now(UTC)
        token = uuid4()
        expires = now + timedelta(seconds=self.lease_seconds)

        approved = exists(select(PlatformChangeRecord.id).where(
            PlatformChangeRecord.id == change_id,
            PlatformChangeRecord.environment == PlatformDeploymentLease.environment,
            PlatformChangeRecord.status == "approved",
            PlatformChangeRecord.approved_by.is_not(None),
            PlatformChangeRecord.approved_by != PlatformChangeRecord.requested_by,
            PlatformChangeRecord.action.in_(("apply", "restart", "migrate")),
            PlatformChangeRecord.source_digest == PlatformDeploymentLease.source_digest,
            PlatformChangeRecord.target_digest == PlatformDeploymentLease.target_digest,
        ))
        current_source = exists(select(PlatformConfigVersion.id).where(
            PlatformConfigVersion.environment == PlatformDeploymentLease.environment,
            PlatformConfigVersion.active.is_(True),
            PlatformConfigVersion.digest == PlatformDeploymentLease.source_digest,
        ))
        staged_target = exists(select(PlatformConfigVersion.id).where(
            PlatformConfigVersion.environment == PlatformDeploymentLease.environment,
            PlatformConfigVersion.active.is_(False),
            PlatformConfigVersion.digest == PlatformDeploymentLease.target_digest,
        ))
        statement = (
            update(PlatformDeploymentLease)
            .where(
                PlatformDeploymentLease.change_id == change_id,
                *([PlatformDeploymentLease.environment == expected_environment] if expected_environment else []),
                PlatformDeploymentLease.status == "ready",
                PlatformDeploymentLease.lease_token.is_(None),
                PlatformDeploymentLease.lease_expires_at.is_(None),
                approved, current_source, staged_target,
            )
            .values(
                status="leased", lease_token=token, owner=owner,
                lease_expires_at=expires, claimed_at=now,
            )
        )
        async with self.sessions() as session, session.begin():
            result = await session.execute(statement)
            if result.rowcount != 1:
                return None
        return DeploymentClaim(change_id, token, owner, expires, expected_environment)

    async def renew(
        self, claim: DeploymentClaim, *, expected_environment: str | None = None,
    ) -> bool:
        """Fence an expired or superseded worker; use DB CAS, not local state."""
        if expected_environment and claim.environment and expected_environment != claim.environment:
            return False
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=self.lease_seconds)
        statement = (
            update(PlatformDeploymentLease)
            .where(
                PlatformDeploymentLease.change_id == claim.change_id,
                *([PlatformDeploymentLease.environment == expected_environment] if expected_environment else []),
                PlatformDeploymentLease.status == "leased",
                PlatformDeploymentLease.lease_token == claim.lease_token,
                *([PlatformDeploymentLease.environment == claim.environment] if claim.environment else []),
                PlatformDeploymentLease.owner == claim.owner,
                PlatformDeploymentLease.lease_expires_at > now,
            )
            .values(lease_expires_at=expires)
        )
        async with self.sessions() as session, session.begin():
            outcome = await session.execute(statement)
            return outcome.rowcount == 1

    async def close(
        self, claim: DeploymentClaim, *, expected_environment: str | None = None,
    ) -> bool:
        """Close only after the control plane persisted a terminal outcome."""
        if expected_environment and claim.environment and expected_environment != claim.environment:
            return False
        now = datetime.now(UTC)
        terminal = exists(select(PlatformChangeRecord.id).where(
            PlatformChangeRecord.id == claim.change_id,
            PlatformChangeRecord.status.in_(("completed", "rolled_back")),
        ))
        statement = (
            update(PlatformDeploymentLease)
            .where(
                PlatformDeploymentLease.change_id == claim.change_id,
                *([PlatformDeploymentLease.environment == expected_environment] if expected_environment else []),
                PlatformDeploymentLease.status == "leased",
                PlatformDeploymentLease.lease_token == claim.lease_token,
                *([PlatformDeploymentLease.environment == claim.environment] if claim.environment else []),
                PlatformDeploymentLease.owner == claim.owner,
                PlatformDeploymentLease.lease_expires_at > now,
                terminal,
            )
            .values(status="closed", lease_token=None, lease_expires_at=None)
        )
        async with self.sessions() as session, session.begin():
            outcome = await session.execute(statement)
            return outcome.rowcount == 1
