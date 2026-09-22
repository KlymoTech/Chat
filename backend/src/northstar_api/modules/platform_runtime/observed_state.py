"""Evidence-derived health, drift, and cost summaries for the control center."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .registry import CapabilityCatalog, CapabilityId


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DriftFinding(_FrozenModel):
    capability_id: CapabilityId
    severity: Literal["warning", "critical"]
    kind: Literal["state", "provider"]
    desired: str
    observed: str
    message: str


class DriftSnapshot(_FrozenModel):
    environment: str
    revision: int
    drift_count: int = Field(ge=0)
    unobserved_count: int = Field(ge=0)
    findings: tuple[DriftFinding, ...] = Field(default_factory=tuple)


class HealthSnapshot(_FrozenModel):
    environment: str
    revision: int
    overall: Literal["healthy", "degraded", "unhealthy", "unknown"]
    healthy: int = Field(ge=0)
    degraded: int = Field(ge=0)
    unhealthy: int = Field(ge=0)
    disabled: int = Field(ge=0)
    unknown: int = Field(ge=0)


class CostSnapshot(_FrozenModel):
    environment: str
    revision: int
    reported_monthly_usd: float = Field(ge=0)
    reported_capabilities: tuple[CapabilityId, ...]
    unreported_capabilities: tuple[CapabilityId, ...]


def detect_drift(catalog: CapabilityCatalog) -> DriftSnapshot:
    findings: list[DriftFinding] = []
    unobserved = 0
    for state in catalog.capabilities:
        capability_id = state.definition.capability_id
        if state.actual_state == "unknown":
            unobserved += 1
        elif state.desired_state == "on" and state.actual_state in {"off", "disabled", "stopped", "absent"}:
            findings.append(
                DriftFinding(
                    capability_id=capability_id,
                    severity="critical" if state.definition.required else "warning",
                    kind="state",
                    desired="on",
                    observed=state.actual_state,
                    message="Observed state does not satisfy desired state.",
                )
            )
        elif state.desired_state == "off" and state.actual_state in {"on", "running", "configured", "healthy"}:
            findings.append(
                DriftFinding(
                    capability_id=capability_id,
                    severity="warning",
                    kind="state",
                    desired="off",
                    observed=state.actual_state,
                    message="Capability is still active after being disabled in desired state.",
                )
            )

        if state.observed_provider and state.observed_provider != state.provider:
            findings.append(
                DriftFinding(
                    capability_id=capability_id,
                    severity="warning",
                    kind="provider",
                    desired=state.provider,
                    observed=state.observed_provider,
                    message="Observed provider differs from the desired provider.",
                )
            )
    return DriftSnapshot(
        environment=catalog.environment,
        revision=catalog.revision,
        drift_count=len(findings),
        unobserved_count=unobserved,
        findings=tuple(findings),
    )


def summarize_health(catalog: CapabilityCatalog) -> HealthSnapshot:
    counts = {"healthy": 0, "degraded": 0, "unhealthy": 0, "disabled": 0, "unknown": 0}
    required_unknown = False
    required_unhealthy = False
    for state in catalog.capabilities:
        counts[state.health] += 1
        if state.definition.required and state.health == "unknown":
            required_unknown = True
        if state.definition.required and state.health == "unhealthy":
            required_unhealthy = True

    if required_unhealthy:
        overall = "unhealthy"
    elif counts["unhealthy"] or counts["degraded"]:
        overall = "degraded"
    elif required_unknown:
        overall = "unknown"
    elif counts["unknown"]:
        overall = "unknown"
    else:
        overall = "healthy"
    return HealthSnapshot(
        environment=catalog.environment,
        revision=catalog.revision,
        overall=overall,
        healthy=counts["healthy"],
        degraded=counts["degraded"],
        unhealthy=counts["unhealthy"],
        disabled=counts["disabled"],
        unknown=counts["unknown"],
    )


def summarize_cost(catalog: CapabilityCatalog) -> CostSnapshot:
    reported: list[CapabilityId] = []
    unreported: list[CapabilityId] = []
    total = 0.0
    for state in catalog.capabilities:
        if state.estimated_monthly_cost_usd is None:
            unreported.append(state.definition.capability_id)
            continue
        total += state.estimated_monthly_cost_usd
        reported.append(state.definition.capability_id)
    return CostSnapshot(
        environment=catalog.environment,
        revision=catalog.revision,
        reported_monthly_usd=round(total, 2),
        reported_capabilities=tuple(reported),
        unreported_capabilities=tuple(unreported),
    )


__all__ = [
    "CostSnapshot",
    "DriftFinding",
    "DriftSnapshot",
    "HealthSnapshot",
    "detect_drift",
    "summarize_cost",
    "summarize_health",
]
