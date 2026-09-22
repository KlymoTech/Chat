"""Capacity budgets derived from process configuration.

This module reports resource ceilings, not a marketing user guarantee. Actual
capacity must be established with a repeatable load test against the target
database, provider quotas, workload mix, and SLOs.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CapacityBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    measured: bool = False
    api_replicas: int = Field(ge=1, le=1000)
    database_connections_per_replica: int = Field(ge=1)
    database_connection_budget: int = Field(ge=1)
    model_concurrency_per_replica: int = Field(ge=1)
    model_concurrency_budget: int = Field(ge=1)
    active_user_guarantee: None = None
    limiting_factors: tuple[str, ...] = Field(min_length=1)


def build_capacity_budget(
    *,
    api_replicas: int = 1,
    database_pool_size: int = 10,
    database_max_overflow: int = 20,
    model_concurrency_per_process: int = 16,
) -> CapacityBudget:
    """Calculate transparent per-process budgets without claiming user capacity."""
    if api_replicas < 1 or api_replicas > 1000:
        raise ValueError("api_replicas must be between 1 and 1000")
    if database_pool_size < 1 or database_max_overflow < 0:
        raise ValueError("database pool values must be positive")
    if model_concurrency_per_process < 1:
        raise ValueError("model concurrency must be positive")
    connections_per_replica = database_pool_size + database_max_overflow
    return CapacityBudget(
        api_replicas=api_replicas,
        database_connections_per_replica=connections_per_replica,
        database_connection_budget=api_replicas * connections_per_replica,
        model_concurrency_per_replica=model_concurrency_per_process,
        model_concurrency_budget=api_replicas * model_concurrency_per_process,
        limiting_factors=(
            "database_connection_limit",
            "model_provider_quota_and_latency",
            "background_worker_database_connections",
            "request_workload_mix_and_slo_targets",
        ),
    )


__all__ = ["CapacityBudget", "build_capacity_budget"]
