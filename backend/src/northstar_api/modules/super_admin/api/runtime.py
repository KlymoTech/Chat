"""Read-only platform capability and change-planning endpoints.

These endpoints expose desired-state information to the super-admin control
center.  They intentionally stop at validation and planning; infrastructure
mutation belongs to an approved deployment controller or GitOps pipeline.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from northstar_api.config import get_settings
from northstar_api.modules.platform_runtime import (
    CapabilityCatalog,
    CapabilityChangeAnalysis,
    CapacityBudget,
    PlatformSpec,
    analyze_capability_change,
    build_capability_catalog,
    build_capacity_budget,
)
from northstar_api.routers.platform_admin import PlatformSystemReadPrincipal

router = APIRouter(prefix="/platform-admin/runtime", tags=["platform runtime"])


class RuntimeChangePlanRequest(BaseModel):
    """Current and desired states supplied by the control center."""

    model_config = ConfigDict(extra="forbid")

    current: PlatformSpec
    desired: PlatformSpec


def _declared_platform_spec() -> PlatformSpec:
    """Translate process configuration into a non-secret runtime snapshot."""
    settings = get_settings()
    is_production = settings.is_production
    redis_configured = bool(settings.redis_url)
    kafka_enabled = settings.kafka_enabled
    ai_enabled = bool(settings.nvidia_api_key)
    return PlatformSpec(
        metadata={"environment": settings.app_env, "revision": 1},
        profile="portable-production" if is_production else "local",
        deployment={"orchestrator": "docker", "region": "local"},
        providers={
            "cache": "redis" if redis_configured else "none",
            "jobs": "rabbitmq" if settings.background_dispatch_enabled else "postgres",
            "events": "kafka" if kafka_enabled else "postgres",
            "storage": "s3" if is_production and settings.s3_configured else "minio",
            "ai": "nvidia" if ai_enabled else "none",
        },
        resources={"redis_provisioned": redis_configured, "kafka_provisioned": kafka_enabled},
        features={"ai": ai_enabled},
    )


@router.get("/capabilities", response_model=CapabilityCatalog)
async def get_runtime_capabilities(_: PlatformSystemReadPrincipal) -> CapabilityCatalog:
    """Return the declared capability state and dependency graph."""
    return build_capability_catalog(_declared_platform_spec())


@router.get("/dependencies")
async def get_runtime_dependencies(_: PlatformSystemReadPrincipal) -> dict[str, object]:
    """Return a stable dependency graph for the control-center graph view."""
    catalog = build_capability_catalog(_declared_platform_spec())
    return catalog.dependencies.model_dump(mode="json")


@router.get("/capacity", response_model=CapacityBudget)
async def get_runtime_capacity(
    _: PlatformSystemReadPrincipal,
    api_replicas: int = Query(default=1, ge=1, le=1000),
) -> CapacityBudget:
    """Return configuration-derived resource budgets, never a user guarantee."""
    settings = get_settings()
    return build_capacity_budget(
        api_replicas=api_replicas,
        database_pool_size=settings.database_pool_size,
        database_max_overflow=settings.database_max_overflow,
        model_concurrency_per_process=settings.model_concurrency_per_process,
    )


@router.post("/changes/plan", response_model=CapabilityChangeAnalysis)
async def plan_runtime_change(
    payload: RuntimeChangePlanRequest,
    _: PlatformSystemReadPrincipal,
) -> CapabilityChangeAnalysis:
    """Validate and analyze a change without applying infrastructure."""
    return analyze_capability_change(payload.current, payload.desired)


__all__ = ["RuntimeChangePlanRequest", "router"]
