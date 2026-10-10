"""Normalize measured runtime signals without contacting a provider."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite


@dataclass(frozen=True)
class CapacitySnapshot:
    observed_at: datetime
    cpu_utilization: float
    memory_utilization: float
    request_rate: float
    error_rate: float
    queue_oldest_age_seconds: float
    replicas: int

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        for field in ("cpu_utilization", "memory_utilization", "error_rate"):
            value = getattr(self, field)
            if not isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{field} must be between zero and one")
        if any(not isfinite(value) or value < 0 for value in (self.request_rate, self.queue_oldest_age_seconds)) or self.replicas < 1:
            raise ValueError("capacity measurements must be nonnegative")


def collect_snapshot(*, cpu: float, memory: float, requests_per_second: float,
                     errors: float, queue_age_seconds: float, replicas: int,
                     observed_at: datetime | None = None) -> CapacitySnapshot:
    return CapacitySnapshot(
        observed_at=observed_at or datetime.now(UTC),
        cpu_utilization=cpu,
        memory_utilization=memory,
        request_rate=requests_per_second,
        error_rate=errors,
        queue_oldest_age_seconds=queue_age_seconds,
        replicas=replicas,
    )
