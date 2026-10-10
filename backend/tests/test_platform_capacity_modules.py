from datetime import UTC, datetime

import pytest

from northstar_api.modules.platform_runtime.adaptive_capacity import (
    CostPolicy,
    capacity_score,
    collect_snapshot,
    evaluate_cost,
    evaluate_safety,
    forecast_queue_age,
    recommend_autoscale,
)
from northstar_api.modules.platform_runtime.adaptive_safety import CapacitySignals


def test_capacity_modules_are_provider_neutral_and_fail_closed() -> None:
    snapshot = collect_snapshot(cpu=.9, memory=.4, requests_per_second=100,
                                errors=0, queue_age_seconds=0, replicas=2,
                                observed_at=datetime.now(UTC))
    assert capacity_score(snapshot) == .9
    assert forecast_queue_age(current_age_seconds=5, arrival_rate=2,
                              service_rate=1, horizon_seconds=10) == 15
    recommendation = recommend_autoscale(
        CapacitySignals(.9, .4, 0, 0, 1), replicas=2, min_replicas=1, max_replicas=3,
    )
    assert recommendation.target_replicas == 3
    assert recommendation.eligible_for_scaling_policy
    assert evaluate_safety(CapacitySignals(.9, .4, 0, 0, 200), replicas=2,
                           min_replicas=1, max_replicas=3).permitted is False


def test_cost_controller_blocks_over_budget() -> None:
    assert evaluate_cost(current_monthly_cost=10, projected_monthly_cost=101,
                         policy=CostPolicy(monthly_budget=100)) == "blocked_budget"


def test_capacity_inputs_reject_nonfinite_measurements() -> None:
    with pytest.raises(ValueError):
        collect_snapshot(cpu=float("nan"), memory=.4, requests_per_second=100,
                         errors=0, queue_age_seconds=0, replicas=2)
    with pytest.raises(ValueError):
        forecast_queue_age(current_age_seconds=0, arrival_rate=float("inf"),
                           service_rate=1, horizon_seconds=10)
    with pytest.raises(ValueError):
        CostPolicy(monthly_budget=float("nan"))
    with pytest.raises(ValueError):
        evaluate_cost(current_monthly_cost=0, projected_monthly_cost=float("inf"),
                      policy=CostPolicy(monthly_budget=100))
