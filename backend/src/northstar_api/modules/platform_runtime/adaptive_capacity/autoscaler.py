"""Recommendation-only autoscaling policy."""
from __future__ import annotations

from dataclasses import dataclass

from ..adaptive_safety import CapacityAction, CapacitySignals, advise_capacity
from .cost_controller import CostPolicy, evaluate_cost


@dataclass(frozen=True)
class AutoscaleRecommendation:
    action: CapacityAction
    target_replicas: int
    reason: str
    eligible_for_scaling_policy: bool


def recommend_autoscale(signals: CapacitySignals, *, replicas: int,
                        min_replicas: int = 2, max_replicas: int = 100,
                        cost_policy: CostPolicy | None = None,
                        current_monthly_cost: float | None = None,
                        projected_monthly_cost: float | None = None) -> AutoscaleRecommendation:
    cost_inputs = (cost_policy, current_monthly_cost, projected_monthly_cost)
    if any(value is not None for value in cost_inputs) and any(
        value is None for value in cost_inputs
    ):
        raise ValueError("autoscale cost evidence must be complete")
    decision = advise_capacity(signals, replicas=replicas, min_replicas=min_replicas,
                               max_replicas=max_replicas)
    target = replicas
    if decision.action is CapacityAction.SCALE_OUT:
        target = min(max_replicas, replicas + 1)
    elif decision.action is CapacityAction.SCALE_IN:
        target = max(min_replicas, replicas - 1)
    eligible = decision.permitted_for_automatic_horizontal_scaling
    reason = decision.reason
    if eligible:
        if cost_policy is None or current_monthly_cost is None or projected_monthly_cost is None:
            eligible, reason = False, "cost_evidence_missing"
        else:
            cost_result = evaluate_cost(
                current_monthly_cost=current_monthly_cost,
                projected_monthly_cost=projected_monthly_cost,
                policy=cost_policy,
            )
            if cost_result != "within_budget":
                eligible, reason = False, f"cost_{cost_result}"
    return AutoscaleRecommendation(decision.action, target, reason, eligible)
