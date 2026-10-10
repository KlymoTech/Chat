"""Fail-closed capacity guidance; recommendations cannot mutate infrastructure."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite


class CapacityAction(str, Enum):
    HOLD = "hold"
    SCALE_OUT = "scale_out"
    SCALE_IN = "scale_in"
    INVESTIGATE = "investigate"


@dataclass(frozen=True)
class CapacitySignals:
    # Utilization is measured as a proportion in [0, 1].
    cpu_utilization: float
    memory_utilization: float
    request_error_rate: float
    queue_oldest_age_seconds: float
    samples_age_seconds: float
    incident_active: bool = False
    backup_healthy: bool = False

    def __post_init__(self) -> None:
        for name in ("cpu_utilization", "memory_utilization", "request_error_rate"):
            value = getattr(self, name)
            if not isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be between zero and one")
        if any(
            not isfinite(value) or value < 0
            for value in (self.queue_oldest_age_seconds, self.samples_age_seconds)
        ):
            raise ValueError("sample age and queue age must be nonnegative")


@dataclass(frozen=True)
class CapacityDecision:
    action: CapacityAction
    reason: str
    permitted_for_automatic_horizontal_scaling: bool
    architectural_change_permitted: bool = False


def advise_capacity(
    signals: CapacitySignals,
    *,
    replicas: int,
    min_replicas: int = 2,
    max_replicas: int = 100,
    high_utilization: float = 0.75,
    low_utilization: float = 0.25,
    max_sample_age_seconds: float = 120,
) -> CapacityDecision:
    """Calculate a conservative recommendation, never a provider API call.

    A single recent sample must never authorize scale-in automatically:
    sustained low utilization and cooldown must be proven by the caller.
    """
    if min_replicas < 1 or max_replicas < min_replicas:
        raise ValueError("invalid replica bounds")
    if replicas < min_replicas or replicas > max_replicas:
        raise ValueError("replicas outside configured bounds")
    if not isfinite(low_utilization) or not isfinite(high_utilization) or not 0 < low_utilization < high_utilization < 1:
        raise ValueError("invalid utilization thresholds")
    if not isfinite(max_sample_age_seconds) or max_sample_age_seconds < 0:
        raise ValueError("invalid maximum sample age")
    if signals.samples_age_seconds > max_sample_age_seconds:
        return CapacityDecision(CapacityAction.INVESTIGATE, "stale_telemetry", False)
    if signals.incident_active:
        return CapacityDecision(CapacityAction.INVESTIGATE, "incident_guard", False)
    if signals.request_error_rate >= 0.05:
        return CapacityDecision(CapacityAction.INVESTIGATE, "elevated_error_rate", False)
    high_pressure = (
        signals.cpu_utilization >= high_utilization
        or signals.memory_utilization >= high_utilization
        or signals.queue_oldest_age_seconds >= 60
    )
    if high_pressure:
        if replicas == max_replicas:
            return CapacityDecision(CapacityAction.INVESTIGATE, "replica_ceiling_reached", False)
        return CapacityDecision(CapacityAction.SCALE_OUT, "resource_or_queue_pressure", True)
    if (
        signals.cpu_utilization <= low_utilization
        and signals.memory_utilization <= low_utilization
        and signals.queue_oldest_age_seconds == 0
        and replicas > min_replicas
    ):
        return CapacityDecision(CapacityAction.SCALE_IN, "candidate_requires_sustained_window_and_cooldown", False)
    return CapacityDecision(CapacityAction.HOLD, "within_operating_band", False)
