"""Contract shared by the control plane and an external deployment worker.

The API publishes this shape through the transactional outbox. Keeping the
contract provider-neutral lets an AWS/GitOps adapter validate an event before
it touches infrastructure and reject stale or malformed work safely.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DeploymentDispatchEvent(BaseModel):
    """Immutable payload for ``platform.runtime.change.approved.v1``."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    change_id: UUID = Field(alias="changeId")
    environment: str = Field(min_length=1, max_length=32)
    action: str = Field(min_length=1, max_length=16)
    classification: str = Field(min_length=1, max_length=32)
    operation: Literal["enable", "disable", "switch", "stop", "destroy"] = "switch"
    requested_capability: str | None = Field(
        alias="requestedCapability",
        default=None,
        min_length=1,
        max_length=80,
    )
    destructive: bool
    source_revision: int = Field(alias="sourceRevision", ge=1)
    target_revision: int = Field(alias="targetRevision", ge=1)
    source_digest: str = Field(alias="sourceDigest", min_length=64, max_length=64)
    target_digest: str = Field(alias="targetDigest", min_length=64, max_length=64)
    idempotency_key: str = Field(alias="idempotencyKey", min_length=8, max_length=128)
    reason: str = Field(min_length=5, max_length=500)
    plan_steps: tuple[str, ...] = Field(alias="planSteps")
    current_spec: dict[str, Any] = Field(alias="currentSpec")
    desired_spec: dict[str, Any] = Field(alias="desiredSpec")


class CapabilityObservationEvidence(BaseModel):
    """Observed provider/runtime evidence reported by a deployment controller."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    capability_id: str = Field(alias="capabilityId", min_length=1, max_length=80)
    actual_state: Literal[
        "unknown",
        "on",
        "off",
        "running",
        "stopped",
        "starting",
        "stopping",
        "configured",
        "degraded",
        "absent",
    ] = Field(alias="actualState")
    health: Literal["healthy", "degraded", "unhealthy", "disabled", "unknown"]
    observed_provider: str | None = Field(
        alias="observedProvider",
        default=None,
        min_length=1,
        max_length=80,
    )
    fallback_active: bool = Field(alias="fallbackActive", default=False)
    health_message: str | None = Field(alias="healthMessage", default=None, max_length=500)
    estimated_monthly_cost_usd: float | None = Field(
        alias="estimatedMonthlyCostUsd",
        default=None,
        ge=0,
        le=10_000_000,
    )


ExecutionPhase = Literal[
    "provisioning",
    "deploying",
    "verifying",
    "stabilizing",
    "completed",
    "failed",
    "rolling_back",
    "rolled_back",
]


class DeploymentExecutionReport(BaseModel):
    """Idempotent stage/health evidence reported by a deployment worker."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    report_key: str = Field(alias="reportKey", min_length=8, max_length=128)
    pipeline: str = Field(min_length=1, max_length=160)
    phase: ExecutionPhase
    source_digest: str = Field(alias="sourceDigest", min_length=64, max_length=64)
    target_digest: str = Field(alias="targetDigest", min_length=64, max_length=64)
    health_result: dict[str, Any] = Field(alias="healthResult", default_factory=dict)
    capability_observations: tuple[CapabilityObservationEvidence, ...] = Field(
        alias="capabilityObservations",
        default_factory=tuple,
    )
    error: str | None = Field(default=None, max_length=500)


__all__ = [
    "CapabilityObservationEvidence",
    "DeploymentDispatchEvent",
    "DeploymentExecutionReport",
    "ExecutionPhase",
]
