"""Operational Platform Control Center endpoints.

These routes expose provider policy, feature flags, drift, health, FinOps
coverage, capability observations, reviewed switch requests, configuration
versions, and rollback planning. They never call Docker, Terraform, or AWS
resource-delete APIs from the browser request path.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select

from northstar_api.dependencies import DBSession
from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.modules.platform_runtime.configuration_state import (
    catalog_with_observations,
    effective_platform_spec,
)
from northstar_api.modules.platform_runtime.contracts import PlatformSpec
from northstar_api.modules.platform_runtime.control_center import (
    CapabilityControlPolicy,
    CapabilityOperation,
    EnvironmentControlPolicy,
    FeatureDefinition,
    ProviderDescriptor,
    apply_operation_policy,
    capability_control_policies,
    capability_control_policy,
    environment_control_policy,
    feature_definitions,
    mutate_capability_spec,
    mutate_feature_spec,
    provider_catalog,
)
from northstar_api.modules.platform_runtime.control_plane import spec_digest
from northstar_api.modules.platform_runtime.observed_state import (
    CostSnapshot,
    DriftSnapshot,
    HealthSnapshot,
    detect_drift,
    summarize_cost,
    summarize_health,
)
from northstar_api.modules.platform_runtime.persistence import (
    PlatformCapabilityRecord,
    PlatformChangeRecord,
    PlatformConfigVersion,
)
from northstar_api.modules.platform_runtime.registry import (
    CapabilityChangeAnalysis,
    CapabilityId,
    analyze_capability_change,
    build_capability_catalog,
)
from northstar_api.routers.platform_admin import PlatformRuntimeManagePrincipal, PlatformSystemReadPrincipal

from .runtime import RuntimeChangeCreateRequest, RuntimeChangeOut, _declared_platform_spec, create_runtime_change

router = APIRouter(prefix="/platform-admin/runtime", tags=["platform control center"])


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlatformSpecSnapshot(_StrictModel):
    spec: PlatformSpec
    digest: str


class CapabilityIntentRequest(_StrictModel):
    operation: CapabilityOperation
    provider: str | None = Field(default=None, min_length=1, max_length=80)


class CapabilityChangeRequest(CapabilityIntentRequest):
    reason: str = Field(min_length=5, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class CapabilityIntentAnalysis(_StrictModel):
    capability_id: CapabilityId
    operation: CapabilityOperation
    policy: CapabilityControlPolicy
    environment_policy: EnvironmentControlPolicy
    current: PlatformSpec
    desired: PlatformSpec
    analysis: CapabilityChangeAnalysis


class FeatureState(_StrictModel):
    definition: FeatureDefinition
    enabled: bool


class FeatureIntentRequest(_StrictModel):
    enabled: bool


class FeatureChangeRequest(FeatureIntentRequest):
    reason: str = Field(min_length=5, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class FeatureIntentAnalysis(_StrictModel):
    feature_id: str
    current_enabled: bool
    desired_enabled: bool
    current: PlatformSpec
    desired: PlatformSpec
    analysis: CapabilityChangeAnalysis
    environment_policy: EnvironmentControlPolicy


class CapabilityObservationRequest(_StrictModel):
    actual_state: Literal[
        "unknown",
        "on",
        "off",
        "running",
        "stopped",
        "starting",
        "stopping",
        "configured",
        "degraded",
        "absent",
    ] = "unknown"
    health: Literal["healthy", "degraded", "unhealthy", "disabled", "unknown"] = "unknown"
    observed_provider: str | None = Field(default=None, min_length=1, max_length=80)
    fallback_active: bool = False
    health_message: str | None = Field(default=None, max_length=500)
    estimated_monthly_cost_usd: float | None = Field(default=None, ge=0, le=10_000_000)


class CapabilityObservationOut(_StrictModel):
    capability_id: str
    environment: str
    desired_provider: str
    desired_state: str
    actual_state: str
    health: str
    observed_provider: str | None
    fallback_active: bool
    health_message: str | None
    estimated_monthly_cost_usd: float | None
    revision: int


class ConfigVersionOut(_StrictModel):
    id: UUID
    environment: str
    revision: int
    digest: str
    active: bool
    created_by: UUID
    created_at: datetime


class RollbackRequest(_StrictModel):
    reason: str = Field(min_length=5, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


async def _effective_spec(session: DBSession, *, environment: str | None = None) -> PlatformSpec:
    try:
        return await effective_platform_spec(
            session,
            _declared_platform_spec(),
            environment=environment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


def _analyze(current: PlatformSpec, desired: PlatformSpec) -> CapabilityChangeAnalysis:
    try:
        return analyze_capability_change(current, desired)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


def _cost_value(metadata: dict[str, object]) -> float | None:
    value = metadata.get("estimatedMonthlyCostUsd")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return float(value)


@router.get("/spec", response_model=PlatformSpecSnapshot)
async def get_effective_runtime_spec(
    _: PlatformSystemReadPrincipal,
    session: DBSession,
    environment: str | None = Query(default=None, min_length=1, max_length=32),
) -> PlatformSpecSnapshot:
    spec = await _effective_spec(session, environment=environment)
    return PlatformSpecSnapshot(spec=spec, digest=spec_digest(spec))


@router.get("/providers", response_model=list[ProviderDescriptor])
async def get_runtime_provider_catalog(_: PlatformSystemReadPrincipal) -> list[ProviderDescriptor]:
    return list(provider_catalog())


@router.get("/policies", response_model=list[CapabilityControlPolicy])
async def get_runtime_control_policies(_: PlatformSystemReadPrincipal) -> list[CapabilityControlPolicy]:
    return list(capability_control_policies())


@router.get("/environments", response_model=list[str])
async def get_runtime_environments(
    _: PlatformSystemReadPrincipal,
    session: DBSession,
) -> list[str]:
    values = {_declared_platform_spec().metadata.environment}
    values.update((await session.scalars(select(PlatformConfigVersion.environment).distinct())).all())
    values.update((await session.scalars(select(PlatformChangeRecord.environment).distinct())).all())
    return sorted(values)


@router.get("/health", response_model=HealthSnapshot)
async def get_runtime_health(
    _: PlatformSystemReadPrincipal,
    session: DBSession,
    environment: str | None = Query(default=None, min_length=1, max_length=32),
) -> HealthSnapshot:
    spec = await _effective_spec(session, environment=environment)
    catalog = await catalog_with_observations(session, spec)
    return summarize_health(catalog)


@router.get("/drift", response_model=DriftSnapshot)
async def get_runtime_drift(
    _: PlatformSystemReadPrincipal,
    session: DBSession,
    environment: str | None = Query(default=None, min_length=1, max_length=32),
) -> DriftSnapshot:
    spec = await _effective_spec(session, environment=environment)
    catalog = await catalog_with_observations(session, spec)
    return detect_drift(catalog)


@router.get("/cost", response_model=CostSnapshot)
async def get_runtime_cost(
    _: PlatformSystemReadPrincipal,
    session: DBSession,
    environment: str | None = Query(default=None, min_length=1, max_length=32),
) -> CostSnapshot:
    spec = await _effective_spec(session, environment=environment)
    catalog = await catalog_with_observations(session, spec)
    return summarize_cost(catalog)


@router.get("/features", response_model=list[FeatureState])
async def get_runtime_features(
    _: PlatformSystemReadPrincipal,
    session: DBSession,
    environment: str | None = Query(default=None, min_length=1, max_length=32),
) -> list[FeatureState]:
    spec = await _effective_spec(session, environment=environment)
    values = spec.features.model_dump()
    return [
        FeatureState(definition=definition, enabled=bool(values[definition.feature_id]))
        for definition in feature_definitions()
    ]


@router.post("/features/{feature_id}/plan", response_model=FeatureIntentAnalysis)
async def plan_runtime_feature_change(
    feature_id: str,
    payload: FeatureIntentRequest,
    _: PlatformSystemReadPrincipal,
    session: DBSession,
) -> FeatureIntentAnalysis:
    current = await _effective_spec(session)
    try:
        desired = mutate_feature_spec(current, feature_id, payload.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    analysis = _analyze(current, desired)
    current_values = current.features.model_dump()
    return FeatureIntentAnalysis(
        feature_id=feature_id,
        current_enabled=bool(current_values[feature_id]),
        desired_enabled=payload.enabled,
        current=current,
        desired=desired,
        analysis=analysis,
        environment_policy=environment_control_policy(current.metadata.environment),
    )


@router.post("/features/{feature_id}/changes", response_model=RuntimeChangeOut, status_code=status.HTTP_201_CREATED)
async def create_runtime_feature_change(
    feature_id: str,
    payload: FeatureChangeRequest,
    principal: PlatformRuntimeManagePrincipal,
    session: DBSession,
) -> RuntimeChangeOut:
    current = await _effective_spec(session)
    try:
        desired = mutate_feature_spec(current, feature_id, payload.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    _analyze(current, desired)
    return await create_runtime_change(
        RuntimeChangeCreateRequest(
            current=current,
            desired=desired,
            reason=payload.reason,
            idempotency_key=payload.idempotency_key,
            operation="enable" if payload.enabled else "disable",
        ),
        principal,
        session,
    )


@router.post("/capabilities/{capability_id}/plan", response_model=CapabilityIntentAnalysis)
async def plan_runtime_capability_change(
    capability_id: CapabilityId,
    payload: CapabilityIntentRequest,
    _: PlatformSystemReadPrincipal,
    session: DBSession,
) -> CapabilityIntentAnalysis:
    current = await _effective_spec(session)
    try:
        desired = mutate_capability_spec(
            current,
            capability_id,
            operation=payload.operation,
            provider=payload.provider,
        )
        policy = capability_control_policy(capability_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    analysis = apply_operation_policy(_analyze(current, desired), payload.operation)
    return CapabilityIntentAnalysis(
        capability_id=capability_id,
        operation=payload.operation,
        policy=policy,
        environment_policy=environment_control_policy(current.metadata.environment),
        current=current,
        desired=desired,
        analysis=analysis,
    )


@router.post(
    "/capabilities/{capability_id}/changes",
    response_model=RuntimeChangeOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_runtime_capability_change(
    capability_id: CapabilityId,
    payload: CapabilityChangeRequest,
    principal: PlatformRuntimeManagePrincipal,
    session: DBSession,
) -> RuntimeChangeOut:
    current = await _effective_spec(session)
    try:
        desired = mutate_capability_spec(
            current,
            capability_id,
            operation=payload.operation,
            provider=payload.provider,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    _analyze(current, desired)
    return await create_runtime_change(
        RuntimeChangeCreateRequest(
            current=current,
            desired=desired,
            reason=payload.reason,
            idempotency_key=payload.idempotency_key,
            operation=payload.operation,
        ),
        principal,
        session,
    )


@router.post(
    "/capabilities/{capability_id}/observations",
    response_model=CapabilityObservationOut,
)
async def report_capability_observation(
    capability_id: CapabilityId,
    payload: CapabilityObservationRequest,
    principal: PlatformRuntimeManagePrincipal,
    session: DBSession,
) -> CapabilityObservationOut:
    spec = await _effective_spec(session)
    catalog = build_capability_catalog(spec)
    desired = next(
        (item for item in catalog.capabilities if item.definition.capability_id == capability_id),
        None,
    )
    if desired is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="capability not found")

    record = await session.scalar(
        select(PlatformCapabilityRecord).where(
            PlatformCapabilityRecord.environment == spec.metadata.environment,
            PlatformCapabilityRecord.capability_id == capability_id,
        )
    )
    if record is None:
        record = PlatformCapabilityRecord(
            environment=spec.metadata.environment,
            capability_id=capability_id,
            provider=desired.provider,
            fallback_provider=desired.definition.fallback_provider,
            desired_state=desired.desired_state,
            actual_state=payload.actual_state,
            health=payload.health,
            revision=spec.metadata.revision,
            metadata_json={},
        )
        session.add(record)
    else:
        record.provider = desired.provider
        record.fallback_provider = desired.definition.fallback_provider
        record.desired_state = desired.desired_state
        record.actual_state = payload.actual_state
        record.health = payload.health
        record.revision = spec.metadata.revision

    metadata = dict(record.metadata_json or {})
    metadata.update(
        {
            "observedProvider": payload.observed_provider,
            "fallbackActive": payload.fallback_active,
            "healthMessage": payload.health_message,
            "estimatedMonthlyCostUsd": payload.estimated_monthly_cost_usd,
        }
    )
    record.metadata_json = metadata
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        actor_user_id=principal.user_id,
        action="platform.runtime.capability.observed",
        entity_type="platform_capability",
        entity_id=capability_id,
        category="system",
        severity="warning" if payload.health in {"degraded", "unhealthy"} else "info",
        after={
            "environment": spec.metadata.environment,
            "actualState": payload.actual_state,
            "health": payload.health,
            "observedProvider": payload.observed_provider,
        },
    )
    await session.commit()
    return CapabilityObservationOut(
        capability_id=capability_id,
        environment=record.environment,
        desired_provider=record.provider,
        desired_state=record.desired_state,
        actual_state=record.actual_state,
        health=record.health,
        observed_provider=payload.observed_provider,
        fallback_active=payload.fallback_active,
        health_message=payload.health_message,
        estimated_monthly_cost_usd=_cost_value(metadata),
        revision=record.revision,
    )


@router.get("/config/versions", response_model=list[ConfigVersionOut])
async def list_runtime_config_versions(
    _: PlatformSystemReadPrincipal,
    session: DBSession,
    environment: str | None = Query(default=None, min_length=1, max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ConfigVersionOut]:
    statement = select(PlatformConfigVersion).order_by(desc(PlatformConfigVersion.revision)).limit(limit)
    if environment:
        statement = statement.where(PlatformConfigVersion.environment == environment)
    rows = (await session.scalars(statement)).all()
    return [
        ConfigVersionOut(
            id=row.id,
            environment=row.environment,
            revision=row.revision,
            digest=row.digest,
            active=row.active,
            created_by=row.created_by,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post("/changes/{change_id}/rollback", response_model=RuntimeChangeOut, status_code=status.HTTP_201_CREATED)
async def create_runtime_rollback(
    change_id: UUID,
    payload: RollbackRequest,
    principal: PlatformRuntimeManagePrincipal,
    session: DBSession,
) -> RuntimeChangeOut:
    original = await session.get(PlatformChangeRecord, change_id)
    if original is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="platform change not found")
    if original.status != "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="only completed changes can be rolled back")
    current = await _effective_spec(session, environment=original.environment)
    if spec_digest(current) != original.target_digest:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="this change is no longer the active configuration; roll back the current revision instead",
        )
    desired = PlatformSpec.model_validate(original.current_spec_json)
    desired = desired.model_copy(
        update={
            "metadata": desired.metadata.model_copy(
                update={"revision": current.metadata.revision + 1}
            )
        }
    )
    created = await create_runtime_change(
        RuntimeChangeCreateRequest(
            current=current,
            desired=desired,
            reason=payload.reason,
            idempotency_key=payload.idempotency_key,
            operation="switch",
        ),
        principal,
        session,
    )
    original.rollback_change_id = created.id
    await session.commit()
    return created


__all__ = ["router"]
