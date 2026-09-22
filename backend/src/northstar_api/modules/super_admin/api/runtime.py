"""Platform capability, change-planning, and approval endpoints.

These endpoints expose desired-state information to the super-admin control
center. They persist an immutable review record and publish an approved plan
through the transactional outbox; infrastructure mutation still belongs to an
approved deployment controller or GitOps pipeline.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError

from northstar_api.config import get_settings
from northstar_api.dependencies import DBSession
from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.modules.platform_runtime import (
    CapabilityCatalog,
    CapabilityChangeAnalysis,
    CapacityBudget,
    ChangeStatus,
    DeploymentDispatchEvent,
    DeploymentExecutionReport,
    PlatformSpec,
    analyze_capability_change,
    approver_is_distinct,
    build_capability_catalog,
    build_capacity_budget,
    spec_digest,
    transition_change,
)
from northstar_api.modules.platform_runtime.configuration_state import (
    activate_configuration_version,
    catalog_with_observations,
    effective_platform_spec,
    ensure_configuration_version,
)
from northstar_api.modules.platform_runtime.persistence import (
    PlatformChangeApproval,
    PlatformChangeRecord,
    PlatformDeploymentExecution,
)
from northstar_api.routers.platform_admin import PlatformRuntimeManagePrincipal, PlatformSystemReadPrincipal
from northstar_api.services.outbox import enqueue_event

router = APIRouter(prefix="/platform-admin/runtime", tags=["platform runtime"])


class RuntimeChangePlanRequest(BaseModel):
    """Current and desired states supplied by the control center."""

    model_config = ConfigDict(extra="forbid")

    current: PlatformSpec
    desired: PlatformSpec


class RuntimeChangeCreateRequest(RuntimeChangePlanRequest):
    reason: str = Field(min_length=5, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    operation: Literal["enable", "disable", "switch", "stop", "destroy"] = "switch"


class RuntimeChangeDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=5, max_length=500)


class RuntimeChangeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    environment: str
    requested_by: UUID
    approved_by: UUID | None
    status: ChangeStatus
    action: str
    classification: str
    operation: str
    requires_approval: bool
    destructive: bool
    source_revision: int
    target_revision: int
    source_digest: str
    target_digest: str
    idempotency_key: str
    reason: str
    plan_steps: tuple[str, ...]
    blockers: tuple[str, ...]
    changed_capabilities: tuple[str, ...]
    impacted_capabilities: tuple[str, ...]
    requested_at: datetime
    approved_at: datetime | None


class RuntimeExecutionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    change_id: UUID
    report_key: str | None
    pipeline: str
    status: str
    source_digest: str | None
    target_digest: str | None
    started_at: datetime | None
    completed_at: datetime | None
    health_result: dict[str, object]
    error: str | None


def _change_response(record: PlatformChangeRecord) -> RuntimeChangeOut:
    impact = record.impact_json or {}
    return RuntimeChangeOut(
        id=record.id,
        environment=record.environment,
        requested_by=record.requested_by,
        approved_by=record.approved_by,
        status=record.status,
        action=record.action,
        classification=record.classification,
        operation=str(impact.get("operation", "switch")),
        requires_approval=record.requires_approval,
        destructive=record.destructive,
        source_revision=record.source_revision,
        target_revision=record.target_revision,
        source_digest=record.source_digest,
        target_digest=record.target_digest,
        idempotency_key=record.idempotency_key,
        reason=record.reason,
        plan_steps=tuple(record.plan_steps or ()),
        blockers=tuple(record.blockers or ()),
        changed_capabilities=tuple(impact.get("changedCapabilities", ())),
        impacted_capabilities=tuple(impact.get("impactedCapabilities", ())),
        requested_at=record.requested_at,
        approved_at=record.approved_at,
    )


def _deployment_dispatch_payload(record: PlatformChangeRecord) -> dict[str, object]:
    """Build the immutable payload consumed by a deployment controller.

    The event intentionally contains the exact source/target digests and
    serialized specifications persisted with the change. A consumer can reject
    stale or replayed work without trusting mutable process configuration.
    """
    payload: dict[str, object] = {
        "changeId": str(record.id),
        "environment": record.environment,
        "action": record.action,
        "classification": record.classification,
        "operation": str((record.impact_json or {}).get("operation", "switch")),
        "destructive": record.destructive,
        "sourceRevision": record.source_revision,
        "targetRevision": record.target_revision,
        "sourceDigest": record.source_digest,
        "targetDigest": record.target_digest,
        "idempotencyKey": record.idempotency_key,
        "reason": record.reason,
        "planSteps": list(record.plan_steps or ()),
        "currentSpec": record.current_spec_json,
        "desiredSpec": record.desired_spec_json,
    }
    # Validate at the producer boundary so an outbox event can never carry a
    # malformed deployment contract even if persistence is changed later.
    return DeploymentDispatchEvent.model_validate(payload).model_dump(by_alias=True, mode="json")


def _execution_response(record: PlatformDeploymentExecution) -> RuntimeExecutionOut:
    return RuntimeExecutionOut(
        id=record.id,
        change_id=record.change_id,
        report_key=record.report_key,
        pipeline=record.pipeline,
        status=record.status,
        source_digest=record.source_digest,
        target_digest=record.target_digest,
        started_at=record.started_at,
        completed_at=record.completed_at,
        health_result=record.health_result_json or {},
        error=record.error,
    )


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
async def get_runtime_capabilities(
    _: PlatformSystemReadPrincipal,
    session: DBSession,
) -> CapabilityCatalog:
    """Return verified desired state overlaid with runtime observations."""
    fallback = _declared_platform_spec()
    spec = await effective_platform_spec(session, fallback)
    return await catalog_with_observations(session, spec)


@router.get("/dependencies")
async def get_runtime_dependencies(
    _: PlatformSystemReadPrincipal,
    session: DBSession,
) -> dict[str, object]:
    """Return a stable dependency graph for the effective desired state."""
    fallback = _declared_platform_spec()
    spec = await effective_platform_spec(session, fallback)
    catalog = build_capability_catalog(spec)
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


@router.post("/changes", response_model=RuntimeChangeOut, status_code=status.HTTP_201_CREATED)
async def create_runtime_change(
    payload: RuntimeChangeCreateRequest,
    principal: PlatformRuntimeManagePrincipal,
    session: DBSession,
) -> RuntimeChangeOut:
    """Persist a reviewable change request; never execute infrastructure."""
    if payload.current.metadata.environment != payload.desired.metadata.environment:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="source and target environments must match")
    analysis = analyze_capability_change(payload.current, payload.desired)
    environment = payload.desired.metadata.environment
    try:
        effective = await effective_platform_spec(session, _declared_platform_spec(), environment=environment)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if spec_digest(effective) != analysis.plan.source_digest:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="source desired state is stale; refresh the control center and plan again",
        )
    if analysis.plan.action == "noop" and payload.operation in {"stop", "destroy"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="infrastructure lifecycle operations require an advanced target revision",
        )
    existing = await session.scalar(
        select(PlatformChangeRecord).where(
            PlatformChangeRecord.environment == environment,
            PlatformChangeRecord.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        if existing.target_digest != analysis.plan.target_digest:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="idempotency key is already in use")
        return _change_response(existing)

    now = datetime.now(UTC)
    destructive = analysis.plan.destructive or payload.operation == "destroy"
    requires_approval = (
        analysis.plan.requires_approval
        or payload.operation in {"stop", "destroy"}
        or environment == "production"
    )
    change_status: ChangeStatus = (
        "rejected"
        if analysis.plan.action == "reject"
        else "completed"
        if analysis.plan.action == "noop"
        else "waiting_approval"
        if requires_approval
        else "approved"
    )
    record = PlatformChangeRecord(
        id=analysis.plan.plan_id if analysis.plan.plan_id else uuid4(),
        environment=environment,
        requested_by=principal.user_id,
        status=change_status,
        action=analysis.plan.action,
        classification=analysis.plan.classification,
        requires_approval=requires_approval,
        destructive=destructive,
        source_revision=analysis.plan.source_revision,
        target_revision=analysis.plan.target_revision,
        source_digest=analysis.plan.source_digest,
        target_digest=analysis.plan.target_digest,
        idempotency_key=payload.idempotency_key,
        reason=payload.reason,
        plan_steps=list(analysis.plan.steps),
        blockers=list(analysis.plan.blockers),
        impact_json={
            "changedCapabilities": list(analysis.changed_capabilities),
            "impactedCapabilities": list(analysis.impacted_capabilities),
            "operation": payload.operation,
        },
        requested_at=now,
        current_spec_json=payload.current.model_dump(mode="json"),
        desired_spec_json=payload.desired.model_dump(mode="json"),
        approved_at=now if change_status in {"completed", "approved"} else None,
        completed_at=now if change_status == "completed" else None,
    )
    session.add(record)
    if change_status not in {"rejected", "completed"}:
        try:
            await ensure_configuration_version(session, record)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        actor_user_id=principal.user_id,
        action="platform.runtime.change.created",
        entity_type="platform_change",
        entity_id=str(record.id),
        category="system",
        severity="warning" if analysis.plan.requires_approval else "info",
        after={"status": change_status, "action": analysis.plan.action, "environment": environment},
        metadata={"reason": payload.reason, "idempotencyKey": payload.idempotency_key},
    )
    if change_status == "approved":
        enqueue_event(
            session,
            tenant_id=principal.tenant_id,
            aggregate_type="platform_change",
            aggregate_id=record.id,
            event_type="platform.runtime.change.approved.v1",
            payload=_deployment_dispatch_payload(record),
        )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        existing = await session.scalar(
            select(PlatformChangeRecord).where(
                PlatformChangeRecord.environment == environment,
                PlatformChangeRecord.idempotency_key == payload.idempotency_key,
            )
        )
        if existing is None:
            raise
        if existing.target_digest != analysis.plan.target_digest:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="idempotency key is already in use",
            ) from exc
        return _change_response(existing)
    return _change_response(record)


@router.get("/changes", response_model=list[RuntimeChangeOut])
async def list_runtime_changes(
    _: PlatformSystemReadPrincipal,
    session: DBSession,
    environment: str | None = Query(default=None, min_length=1, max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[RuntimeChangeOut]:
    """List reviewable changes for the control-center history screen."""
    statement = select(PlatformChangeRecord).order_by(desc(PlatformChangeRecord.requested_at)).limit(limit)
    if environment:
        statement = statement.where(PlatformChangeRecord.environment == environment)
    records = (await session.scalars(statement)).all()
    return [_change_response(record) for record in records]


@router.get("/changes/{change_id}", response_model=RuntimeChangeOut)
async def get_runtime_change(
    change_id: UUID,
    _: PlatformSystemReadPrincipal,
    session: DBSession,
) -> RuntimeChangeOut:
    """Return one change and its immutable plan metadata."""
    record = await session.get(PlatformChangeRecord, change_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="platform change not found")
    return _change_response(record)


@router.get("/changes/{change_id}/executions", response_model=list[RuntimeExecutionOut])
async def list_runtime_executions(
    change_id: UUID,
    _: PlatformSystemReadPrincipal,
    session: DBSession,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[RuntimeExecutionOut]:
    """Return deployment evidence reported for a persisted change."""
    if await session.get(PlatformChangeRecord, change_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="platform change not found")
    records = (
        await session.scalars(
            select(PlatformDeploymentExecution)
            .where(PlatformDeploymentExecution.change_id == change_id)
            .order_by(desc(PlatformDeploymentExecution.started_at))
            .limit(limit)
        )
    ).all()
    return [_execution_response(record) for record in records]


@router.post("/changes/{change_id}/executions", response_model=RuntimeExecutionOut, status_code=status.HTTP_201_CREATED)
async def report_runtime_execution(
    change_id: UUID,
    payload: DeploymentExecutionReport,
    principal: PlatformRuntimeManagePrincipal,
    session: DBSession,
) -> RuntimeExecutionOut:
    """Persist one idempotent deployment stage and health report.

    This endpoint records evidence only. Provider-specific mutation remains in
    the external deployment controller that consumed the approved outbox event.
    """
    record = await session.get(PlatformChangeRecord, change_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="platform change not found")
    existing = await session.scalar(
        select(PlatformDeploymentExecution).where(
            PlatformDeploymentExecution.change_id == change_id,
            PlatformDeploymentExecution.report_key == payload.report_key,
        )
    )
    if existing is not None:
        if (
            existing.source_digest != payload.source_digest
            or existing.target_digest != payload.target_digest
            or existing.pipeline != payload.pipeline
            or existing.status != payload.phase
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="execution report key is already in use")
        return _execution_response(existing)

    current_status: ChangeStatus = record.status
    try:
        transition_change(current_status, payload.phase)
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"cannot report phase {payload.phase} from change status {record.status}",
        ) from exc
    if record.source_digest != payload.source_digest or record.target_digest != payload.target_digest:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="execution digest does not match the approved plan")

    now = datetime.now(UTC)
    terminal = payload.phase in {"completed", "failed", "rolled_back"}
    execution = PlatformDeploymentExecution(
        change_id=change_id,
        report_key=payload.report_key,
        pipeline=payload.pipeline,
        status=payload.phase,
        source_digest=payload.source_digest,
        target_digest=payload.target_digest,
        started_at=now,
        completed_at=now if terminal else None,
        health_result_json=payload.health_result,
        error=payload.error,
    )
    record.status = payload.phase
    record.started_at = record.started_at or now
    if terminal:
        record.completed_at = now
    if payload.phase == "completed":
        try:
            await activate_configuration_version(session, record)
        except ValueError as exc:
            await session.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.add(execution)
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        actor_user_id=principal.user_id,
        action="platform.runtime.change.execution_reported",
        entity_type="platform_change",
        entity_id=str(change_id),
        category="system",
        severity="error" if payload.phase == "failed" else "info",
        after={"status": payload.phase, "pipeline": payload.pipeline},
        metadata={"reportKey": payload.report_key, "health": payload.health_result},
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        existing = await session.scalar(
            select(PlatformDeploymentExecution).where(
                PlatformDeploymentExecution.change_id == change_id,
                PlatformDeploymentExecution.report_key == payload.report_key,
            )
        )
        if existing is None:
            raise
        if (
            existing.source_digest != payload.source_digest
            or existing.target_digest != payload.target_digest
            or existing.pipeline != payload.pipeline
            or existing.status != payload.phase
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="execution report key is already in use") from exc
        return _execution_response(existing)
    return _execution_response(execution)


@router.post("/changes/{change_id}/approve", response_model=RuntimeChangeOut)
async def approve_runtime_change(
    change_id: UUID,
    payload: RuntimeChangeDecisionRequest,
    principal: PlatformRuntimeManagePrincipal,
    session: DBSession,
) -> RuntimeChangeOut:
    """Approve a change only when the approver differs from its requestor."""
    record = await session.get(PlatformChangeRecord, change_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="platform change not found")
    if record.status != "waiting_approval":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="platform change is not awaiting approval")
    if not approver_is_distinct(record.requested_by, principal.user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="requestor cannot approve the same change")
    transition_change(record.status, "approved")
    now = datetime.now(UTC)
    record.status = "approved"
    record.approved_by = principal.user_id
    record.approved_at = now
    session.add(PlatformChangeApproval(
        change_id=record.id,
        approver_id=principal.user_id,
        decision="approved",
        reason=payload.reason,
        created_at=now,
    ))
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="platform_change",
        aggregate_id=record.id,
        event_type="platform.runtime.change.approved.v1",
        payload=_deployment_dispatch_payload(record),
    )
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        actor_user_id=principal.user_id,
        action="platform.runtime.change.approved",
        entity_type="platform_change",
        entity_id=str(record.id),
        category="security",
        severity="warning",
        after={"status": record.status},
        metadata={"reason": payload.reason},
    )
    await session.commit()
    return _change_response(record)


@router.post("/changes/{change_id}/reject", response_model=RuntimeChangeOut)
async def reject_runtime_change(
    change_id: UUID,
    payload: RuntimeChangeDecisionRequest,
    principal: PlatformRuntimeManagePrincipal,
    session: DBSession,
) -> RuntimeChangeOut:
    """Reject an unapproved change and retain the reason for audit."""
    record = await session.get(PlatformChangeRecord, change_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="platform change not found")
    if record.status != "waiting_approval":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="platform change is not awaiting approval")
    transition_change(record.status, "rejected")
    now = datetime.now(UTC)
    record.status = "rejected"
    record.completed_at = now
    session.add(PlatformChangeApproval(
        change_id=record.id,
        approver_id=principal.user_id,
        decision="rejected",
        reason=payload.reason,
        created_at=now,
    ))
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        actor_user_id=principal.user_id,
        action="platform.runtime.change.rejected",
        entity_type="platform_change",
        entity_id=str(record.id),
        category="security",
        severity="warning",
        after={"status": record.status},
        metadata={"reason": payload.reason},
    )
    await session.commit()
    return _change_response(record)


__all__ = [
    "RuntimeChangeCreateRequest",
    "RuntimeChangeDecisionRequest",
    "RuntimeChangeOut",
    "RuntimeChangePlanRequest",
    "RuntimeExecutionOut",
    "router",
]
