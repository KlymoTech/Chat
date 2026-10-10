"""Fail-closed guards for adaptive recommendations."""
from __future__ import annotations

from dataclasses import dataclass

from ..adaptive_safety import CapacitySignals, advise_capacity


@dataclass(frozen=True)
class SafetyDecision:
    permitted: bool
    reason: str


def evaluate_safety(signals: CapacitySignals, *, replicas: int,
                    min_replicas: int, max_replicas: int) -> SafetyDecision:
    decision = advise_capacity(signals, replicas=replicas,
                               min_replicas=min_replicas, max_replicas=max_replicas)
    return SafetyDecision(decision.permitted_for_automatic_horizontal_scaling,
                          decision.reason)
