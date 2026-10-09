"""Machine-authenticated deployment operations with mandatory durable auditing.

Every admitted operation writes a serialized intent BEFORE a database action,
then an immutable outcome. An interrupted action leaves an unresolved intent
and is blocked from automatic retry until independent reconciliation. No AWS
executor or HTTP route is activated here.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar
from uuid import UUID

from .deployment_leases import DeploymentClaim, DeploymentLeaseService
from .deployment_machine_identity import (
    DeploymentMachinePrincipal,
    MachineAuthenticationError,
    WorkerAction,
    authenticate_deployment_worker,
)
from .deployment_step_journal import DeploymentStepClaim, DeploymentStepJournal
from .deployment_worker_audit import DeploymentWorkerAuditTrail

T = TypeVar("T")


@dataclass(frozen=True)
class DeploymentWorkerPolicy:
    public_key_pem: bytes
    issuer: str
    audience: str
    environment: str
    allowed_subject: str

    def __post_init__(self) -> None:
        if not all((
            self.public_key_pem, self.issuer, self.audience,
            self.environment, self.allowed_subject,
        )):
            raise ValueError("deployment worker policy must be fully configured")


class DeploymentWorkerOperations:
    """Require fresh machine authorization and committed audit intent per action."""

    def __init__(
        self,
        *,
        policy: DeploymentWorkerPolicy,
        leases: DeploymentLeaseService,
        journal: DeploymentStepJournal,
        audit: DeploymentWorkerAuditTrail,
    ) -> None:
        if audit is None:
            raise ValueError("durable deployment audit trail is required")
        self.policy = policy
        self.leases = leases
        self.journal = journal
        self.audit = audit

    def _authorize(self, token: str, action: WorkerAction) -> DeploymentMachinePrincipal:
        return authenticate_deployment_worker(
            token,
            public_key_pem=self.policy.public_key_pem,
            issuer=self.policy.issuer,
            audience=self.policy.audience,
            environment=self.policy.environment,
            allowed_subject=self.policy.allowed_subject,
            action=action,
        )

    @staticmethod
    def _claim_owned(claim: DeploymentClaim, principal: DeploymentMachinePrincipal) -> None:
        if claim.owner != principal.subject or claim.environment != principal.environment:
            raise MachineAuthenticationError("claim does not belong to this worker environment")

    async def _perform(
        self, *, token: str, action: WorkerAction, change_id: UUID,
        operation: Callable[[DeploymentMachinePrincipal], Awaitable[T]],
        claim: DeploymentClaim | None = None,
        step_index: int | None = None,
        unknown_on_success: bool = False,
    ) -> T:
        principal = self._authorize(token, action)
        if claim is not None:
            self._claim_owned(claim, principal)
        attempt = await self.audit.begin(
            principal=principal, change_id=change_id, action=action, step_index=step_index,
        )
        try:
            result = await operation(principal)
        except Exception:
            # A side effect may have happened even if the response was lost.
            # A failed outcome append leaves the intent unresolved (fail closed).
            await self.audit.finish(attempt, outcome="unknown")
            raise
        await self.audit.finish(
            attempt, outcome=(
                "unknown" if unknown_on_success and result else
                "accepted" if result else "rejected"
            ),
        )
        return result

    async def claim(self, token: str, change_id: UUID) -> DeploymentClaim | None:
        return await self._perform(
            token=token, action="claim", change_id=change_id,
            operation=lambda principal: self.leases.claim(
                change_id, owner=principal.subject, expected_environment=principal.environment,
            ),
        )

    async def renew(self, token: str, claim: DeploymentClaim) -> bool:
        return await self._perform(
            token=token, action="renew", change_id=claim.change_id, claim=claim,
            operation=lambda principal: self.leases.renew(
                claim, expected_environment=principal.environment,
            ),
        )

    async def begin_step(
        self, token: str, claim: DeploymentClaim, index: int,
    ) -> DeploymentStepClaim | None:
        return await self._perform(
            token=token, action="begin", change_id=claim.change_id, claim=claim,
            step_index=index, operation=lambda _: self.journal.begin_step(claim, index),
        )

    async def verify_step(
        self, token: str, claim: DeploymentClaim, index: int, *,
        signed_attestation: str,
    ) -> bool:
        return await self._perform(
            token=token, action="verify", change_id=claim.change_id, claim=claim,
            step_index=index, operation=lambda _: self.journal.verify_step(
                claim, index, signed_attestation=signed_attestation,
            ),
        )

    async def mark_unknown(
        self, token: str, claim: DeploymentClaim, index: int, *, reason: str,
    ) -> bool:
        return await self._perform(
            token=token, action="mark_unknown", change_id=claim.change_id, claim=claim,
            step_index=index, unknown_on_success=True,
            operation=lambda _: self.journal.mark_unknown(claim, index, reason=reason),
        )

    async def close(self, token: str, claim: DeploymentClaim) -> bool:
        return await self._perform(
            token=token, action="close", change_id=claim.change_id, claim=claim,
            operation=lambda principal: self.leases.close(
                claim, expected_environment=principal.environment,
            ),
        )
