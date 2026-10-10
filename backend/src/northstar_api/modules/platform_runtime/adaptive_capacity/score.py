"""Transparent score used for recommendations, never for authorization."""
from __future__ import annotations

from .collector import CapacitySnapshot


def capacity_score(snapshot: CapacitySnapshot) -> float:
    """Return a bounded pressure score from 0 (idle) to 1 (saturated)."""
    queue_pressure = min(snapshot.queue_oldest_age_seconds / 60, 1)
    return min(1.0, max(snapshot.cpu_utilization, snapshot.memory_utilization,
                         snapshot.error_rate * 20, queue_pressure))
