"""Machine-authenticated facade over fenced Northstar deployment operations.

Callers cannot choose their identity, environment, machine trust key, or step
verifier key. This facade deliberately contains no AWS SDK, shell commands,
HTTP route registration, or permission to execute cloud side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .deployment_leases import DeploymentClaim, DeploymentLeaseService
from .deployment_machine_identity import (
    DeploymentMachinePrincipal,
    MachineAuthenticationError,
    WorkerAction,
    authenticate_deployment_worker,
)
from .deployment_step_journal import DeploymentStepClaim, DeploymentStepJournal


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
    """Require fresh machine authorization for each bounded database operation."""

    def __init__(
        self,
        *,
        policy: DeploymentWorkerPolicy,
        leases: DeploymentLeaseService,
        journal: DeploymentStepJournal,
    ) -> None:
        self.policy = policy
        self.leases = leases
        self.journal = journal

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

    async def claim(self, token: str, change_id: UUID) -> DeploymentClaim | None:
        principal = self._authorize(token, "claim")
        return await self.leases.claim(
            change_id, owner=principal.subject, expected_environment=principal.environment,
        )

    async def renew(self, token: str, claim: DeploymentClaim) -> bool:
        principal = self._authorize(token, "renew")
        self._claim_owned(claim, principal)
        return await self.leases.renew(claim, expected_environment=principal.environment)

    async def begin_step(
        self, token: str, claim: DeploymentClaim, index: int,
    ) -> DeploymentStepClaim | None:
        principal = self._authorize(token, "begin")
        self._claim_owned(claim, principal)
        return await self.journal.begin_step(claim, index)

    async def verify_step(
        self, token: str, claim: DeploymentClaim, index: int, *,
        signed_attestation: str,
    ) -> bool:
        principal = self._authorize(token, "verify")
        self._claim_owned(claim, principal)
        return await self.journal.verify_step(
            claim, index, signed_attestation=signed_attestation,
        )

    async def mark_unknown(
        self, token: str, claim: DeploymentClaim, index: int, *, reason: str,
    ) -> bool:
        principal = self._authorize(token, "mark_unknown")
        self._claim_owned(claim, principal)
        return await self.journal.mark_unknown(claim, index, reason=reason)

    async def close(self, token: str, claim: DeploymentClaim) -> bool:
        principal = self._authorize(token, "close")
        self._claim_owned(claim, principal)
        return await self.leases.close(claim, expected_environment=principal.environment)
