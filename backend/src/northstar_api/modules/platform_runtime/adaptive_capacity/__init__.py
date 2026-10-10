"""Provider-neutral adaptive capacity recommendations."""

from .autoscaler import AutoscaleRecommendation, recommend_autoscale
from .collector import CapacitySnapshot, collect_snapshot
from .cost_controller import CostPolicy, evaluate_cost
from .forecast import forecast_queue_age
from .safety_controller import SafetyDecision, evaluate_safety
from .score import capacity_score

__all__ = [
    "AutoscaleRecommendation", "CapacitySnapshot", "CostPolicy", "SafetyDecision",
    "capacity_score", "collect_snapshot", "evaluate_cost", "evaluate_safety",
    "forecast_queue_age", "recommend_autoscale",
]
