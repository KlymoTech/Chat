"""Budget guard for recommendations; prices are supplied as measured inputs."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class CostPolicy:
    monthly_budget: float
    warning_fraction: float = .8
    hard_fraction: float = 1.0

    def __post_init__(self) -> None:
        if not all(isfinite(value) for value in (self.monthly_budget, self.warning_fraction, self.hard_fraction)) or self.monthly_budget < 0 or not 0 < self.warning_fraction <= self.hard_fraction:
            raise ValueError("invalid cost policy")


def evaluate_cost(*, current_monthly_cost: float, projected_monthly_cost: float,
                  policy: CostPolicy) -> str:
    if any(not isfinite(value) or value < 0 for value in (current_monthly_cost, projected_monthly_cost)):
        raise ValueError("costs must be nonnegative")
    if projected_monthly_cost > policy.monthly_budget * policy.hard_fraction:
        return "blocked_budget"
    if projected_monthly_cost > policy.monthly_budget * policy.warning_fraction:
        return "warning_budget"
    return "within_budget"
