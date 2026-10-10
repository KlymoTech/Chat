"""Small, explainable forecasts for queue pressure."""
from __future__ import annotations

from math import isfinite


def forecast_queue_age(*, current_age_seconds: float, arrival_rate: float,
                       service_rate: float, horizon_seconds: float) -> float:
    if any(not isfinite(value) or value < 0 for value in (current_age_seconds, arrival_rate, service_rate, horizon_seconds)):
        raise ValueError("forecast inputs must be nonnegative")
    if service_rate == 0:
        return current_age_seconds if arrival_rate == 0 else float("inf")
    # This is intentionally a first-order advisory model; qualification must
    # replace it with measured workload evidence.
    drift = (arrival_rate / service_rate - 1) * horizon_seconds
    return max(0.0, current_age_seconds + drift)
