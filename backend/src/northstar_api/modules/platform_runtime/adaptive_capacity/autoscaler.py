"""Recommendation-only autoscaling policy."""
from __future__ import annotations

from dataclasses import dataclass

from ..adaptive_safety import CapacityAction, CapacitySignals, advise_capacity


@dataclass(frozen=True)
class AutoscaleRecommendation:
    action: CapacityAction
    target_replicas: int
    reason: str
    eligible_for_scaling_policy: bool


def recommend_autoscale(signals: CapacitySignals, *, replicas: int,
                        min_replicas: int = 2, max_replicas: int = 100) -> AutoscaleRecommendation:
    decision = advise_capacity(signals, replicas=replicas, min_replicas=min_replicas,
                               max_replicas=max_replicas)
    target = replicas
    if decision.action is CapacityAction.SCALE_OUT:
        target = min(max_replicas, replicas + 1)
    elif decision.action is CapacityAction.SCALE_IN:
        target = max(min_replicas, replicas - 1)
    return AutoscaleRecommendation(decision.action, target, decision.reason,
                                   decision.permitted_for_automatic_horizontal_scaling)
