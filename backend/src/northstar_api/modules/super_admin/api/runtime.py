"""Platform capability, change-planning, and approval endpoints.

These endpoints expose desired-state information to the super-admin control
center. They persist an immutable review record and publish an approved plan
through the transactional outbox; infrastructure mutation still belongs to an
approved deployment controller or GitOps pipeline.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select, update
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
    transition_change,
)
from northstar_api.modules.platform_runtime.persistence import (
    PlatformChangeApproval,
    PlatformChangeRecord,
    PlatformConfigVersion,
    PlatformDeploymentExecution,
)
from northstar_api.routers.platform_admin import PlatformRuntimeManagePrincipal, PlatformSystemReadPrincipal
from northstar_api.services.outbox import enqueue_event

from northstar_api.modules.platform_runtime.tiers import (
    PlatformTier, TIERS, plan_tier_transition,
)
from northstar_api.modules.platform_runtime.governed_switches import classify_transition, SwitchClass
from northstar_api.modules.platform_runtime.qualification import verify_qualification_proofs
from northstar_api.modules.platform_runtime.approval_integrity import persisted_change_integrity_blockers
from northstar_api.modules.platform_runtime.control_plane import spec_digest
from northstar_api.modules.platform_runtime.validation import validate_platform_spec
from northstar_api.modules.platform_runtime.adaptive_safety import (
    CapacitySignals, advise_capacity,
)

router = APIRouter(prefix="/platform-admin/runtime", tags=["platform runtime"])

class TierPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: PlatformTier
    target: PlatformTier


class CapacityPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signals: dict[str, float | bool]
    replicas: int = Field(ge=2, le=100)


@router.get("/tiers")
async def list_runtime_tiers(_: PlatformSystemReadPrincipal) -> dict[str, object]:
    """Read-only architecture definitions; these are not measured capacities."""
    return {"tiers": [asdict(tier) for tier in TIERS], "qualified": False}


@router.post("/tiers/preview")
async def preview_tier_change(
    payload: TierPreviewRequest,
    _: PlatformSystemReadPrincipal,
) -> dict[str, object]:
    """Preview required evidence; the endpoint cannot approve or execute."""
    return asdict(plan_tier_transition(payload.source, payload.target))


@router.post("/capacity/preview")
async def preview_capacity_action(
    payload: CapacityPreviewRequest,
    _: PlatformSystemReadPrincipal,
) -> dict[str, object]:
    """Advisory-only scaling recommendation with no AWS mutation."""
    try:
        signals = CapacitySignals(**payload.signals)
        return asdict(advise_capacity(signals, replicas=payload.replicas))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="invalid capacity signal input") from exc





class RuntimeChangePlanRequest(BaseModel):
    """Current and desired states supplied by the control center."""

    model_config = ConfigDict(extra="forbid")

    current: PlatformSpec
    desired: PlatformSpec


@router.post("/changes/governance-preview")
async def preview_change_governance(
    payload: RuntimeChangePlanRequest,
    _: PlatformSystemReadPrincipal,
) -> dict[str, object]:
    """Preview A/B/C/D/L/E evidence gates; never authorize a deployment."""
    return asdict(classify_transition(payload.current, payload.desired))


class RuntimeChangeCreateRequest(RuntimeChangePlanRequest):
    reason: str = Field(min_length=5, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class RuntimeChangeDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=5, max_length=500)
    evidence: tuple[str, ...] = Field(default_factory=tuple, max_length=32)


class RuntimeChangeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    environment: str
    requested_by: UUID
    approved_by: UUID | None
    status: ChangeStatus
    action: str
    classification: str
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


@router.get("/queue/brokers/sqs/health")
async def read_platform_sqs_health(
    _: PlatformSystemReadPrincipal,
) -> dict[str, object]:
    """Read-only health of the configured shared SQS queue.

    Counts are queue-wide infrastructure metrics, not tenant-filtered values.
    The URL is deployment-configured, never supplied by an HTTP caller.
    """
    import boto3

    from northstar_api.modules.platform_runtime.broker_health import probe_sqs

    queue_url = os.environ.get("PLATFORM_QUEUE_HEALTH_SQS_URL", "")
    if not queue_url:
        return {
            "provider": "sqs", "status": "unconfigured",
            "scope": "shared_queue", "detail": "probe_not_configured",
        }
    # Creating a client does not call AWS. Probe execution is bounded and
    # catches provider/credential failures without revealing secret values.
    try:
        client = boto3.client("sqs", region_name=get_settings().s3_region)
        result = await probe_sqs(client, queue_url, timeout_seconds=3.0)
    except Exception:
        return {
            "provider": "sqs", "status": "unavailable",
            "scope": "shared_queue", "detail": "probe_initialization_failed",
        }
    return {"scope": "shared_queue", **result.as_json()}


@router.get("/queue/brokers/rabbitmq/health")
async def read_platform_rabbitmq_health(
    _: PlatformSystemReadPrincipal,
) -> dict[str, object]:
    """Probe a deployment-configured shared RabbitMQ queue, never a caller URL."""
    import asyncio

    from kombu import Connection

    from northstar_api.modules.platform_runtime.broker_health import probe_rabbitmq

    queue_name = os.environ.get("PLATFORM_QUEUE_HEALTH_RABBITMQ_QUEUE", "")
    if not queue_name:
        return {
            "provider": "rabbitmq", "status": "unconfigured",
            "scope": "shared_queue", "detail": "probe_not_configured",
        }
    if len(queue_name) > 200 or any(ch.isspace() for ch in queue_name):
        return {
            "provider": "rabbitmq", "status": "unavailable",
            "scope": "shared_queue", "detail": "invalid_probe_configuration",
        }
    connection = None
    try:
        connection = Connection(
            get_settings().rabbitmq_url,
            connect_timeout=2,
            transport_options={"socket_timeout": 2},
        )
        # Connection setup uses blocking kombu APIs; run away from the event loop.
        await asyncio.wait_for(asyncio.to_thread(connection.connect), timeout=3.0)
        result = await probe_rabbitmq(connection, queue_name=queue_name, timeout_seconds=3.0)
        return {"scope": "shared_queue", **result.as_json()}
    except Exception:
        return {
            "provider": "rabbitmq", "status": "unavailable",
            "scope": "shared_queue", "detail": "probe_initialization_failed",
        }
    finally:
        if connection is not None:
            try:
                await asyncio.wait_for(asyncio.to_thread(connection.release), timeout=3.0)
            except Exception:
                pass


@router.get("/queue/alerts")
async def read_platform_queue_alerts(
    principal: PlatformSystemReadPrincipal,
    session: DBSession,
) -> dict[str, object]:
    """Read-only alert snapshot; delivery/deduplication are not claimed."""
    from northstar_api.modules.platform_runtime.queue_alerts import classify_queue_alerts

    overview = await read_platform_queue_overview(principal, session)
    alerts = classify_queue_alerts(overview)
    return {
        "tenant_id": str(principal.tenant_id),
        "alerts": [item.as_json() for item in alerts],
        "source_status": overview["status"],
        "delivery_configured": False,
    }


@router.get("/queue/overview")
async def read_platform_queue_overview(
    principal: PlatformSystemReadPrincipal,
    session: DBSession,
) -> dict[str, object]:
    """Aggregate tenant-specific job health and explicitly shared broker probes.

    A healthy broker cannot turn a degraded durable backlog healthy.
    Unconfigured probes remain unknown, never healthy by inference.
    """
    import asyncio

    if principal.tenant_id is None:
        raise HTTPException(status_code=403, detail="tenant scope required")
    durable = await read_platform_queue_health(principal, session)
    broker_results = await asyncio.gather(
        read_platform_sqs_health(principal),
        read_platform_rabbitmq_health(principal),
        return_exceptions=True,
    )
    brokers: dict[str, dict[str, object]] = {}
    for name, result in zip(("sqs", "rabbitmq"), broker_results, strict=True):
        if isinstance(result, BaseException):
            brokers[name] = {
                "provider": name, "status": "unavailable",
                "scope": "shared_queue", "detail": "probe_failed",
            }
        else:
            brokers[name] = result

    # Broker probes may be unconfigured because the provider is inactive.
    # That is not proof of an outage, but must not be reported as healthy.
    states = {str(item["status"]) for item in brokers.values()}
    if durable["status"] == "degraded" or "unavailable" in states:
        status_label = "degraded"
    elif "unconfigured" in states:
        status_label = "unknown"
    else:
        status_label = str(durable["status"])
    return {
        "status": status_label,
        "tenant_id": str(principal.tenant_id),
        "durable_jobs": durable,
        "brokers": brokers,
        "broker_scope": "shared_queue",
        "qualified": False,
    }


@router.get("/queue/health")
async def read_platform_queue_health(
    principal: PlatformSystemReadPrincipal,
    session: DBSession,
) -> dict[str, object]:
    """Tenant-scoped durable queue state; broker probe status remains unknown."""
    from northstar_api.modules.platform_runtime.queue_health import assess_queue_health

    if principal.tenant_id is None:
        raise HTTPException(status_code=403, detail="tenant scope required")
    health = await assess_queue_health(session, tenant_id=principal.tenant_id)
    return health.as_json()


class QueueDeadLetterReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=12, max_length=500)


@router.post("/queue/dead-letters/{job_id}/replay")
async def replay_platform_dead_letter(
    job_id: UUID,
    payload: QueueDeadLetterReplayRequest,
    principal: PlatformRuntimeManagePrincipal,
    session: DBSession,
) -> dict[str, object]:
    """Authorized, tenant-scoped replay with a transactional audit record.

    This endpoint only requeues a dead-letter job; it never publishes directly.
    """
    from northstar_api.modules.platform_runtime.queue_persistence import DurableQueueRecord

    tenant_id = principal.tenant_id
    if tenant_id is None:
        raise HTTPException(status_code=403, detail="tenant scope required")
    if not payload.reason.strip():
        raise HTTPException(status_code=422, detail="documented reason required")
    result = await session.execute(
        update(DurableQueueRecord)
        .where(
            DurableQueueRecord.id == job_id,
            DurableQueueRecord.tenant_id == tenant_id,
            DurableQueueRecord.status == "dead_letter",
            DurableQueueRecord.lease_token.is_(None),
        )
        .values(
            status="queued",
            attempts=0,
            available_at=datetime.now(UTC),
            published_reference=None,
            lease_expires_at=None,
        )
    )
    if result.rowcount != 1:
        await session.rollback()
        raise HTTPException(status_code=409, detail="tenant-scoped job unavailable for replay")
    record_audit_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=principal.user_id,
        action="platform.queue.dead_letter_replayed",
        entity_type="platform_durable_job",
        entity_id=str(job_id),
        category="security",
        severity="warning",
        after={"state": "queued", "tenantId": str(tenant_id)},
        metadata={"reason": payload.reason.strip()},
    )
    await session.commit()
    return {"jobId": str(job_id), "state": "queued", "replayed": True}


class DesiredStateDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    desired: PlatformSpec
    reason: str = Field(min_length=5, max_length=500)


@router.post("/desired-state/versions", status_code=status.HTTP_201_CREATED)
async def create_desired_state_draft(
    payload: DesiredStateDraftRequest,
    principal: PlatformRuntimeManagePrincipal,
    session: DBSession,
) -> dict[str, object]:
    """Store an immutable *inactive* revision; never activate or deploy it.

    Activation must go through a separate reviewed and qualified change.
    Concurrent revision reuse fails rather than overwriting existing state.
    """
    spec = payload.desired
    validate_platform_spec(spec)
    environment = spec.metadata.environment
    revision = spec.metadata.revision
    latest = await session.scalar(
        select(PlatformConfigVersion)
        .where(PlatformConfigVersion.environment == environment)
        .order_by(desc(PlatformConfigVersion.revision))
        .limit(1)
    )
    if latest is not None and revision <= latest.revision:
        raise HTTPException(status_code=409, detail="desired-state revision must advance")
    record = PlatformConfigVersion(
        id=uuid4(),
        environment=environment,
        revision=revision,
        digest=spec_digest(spec),
        configuration_json=spec.model_dump(mode="json"),
        created_by=principal.user_id,
        active=False,
        created_at=datetime.now(UTC),
    )
    session.add(record)
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        actor_user_id=principal.user_id,
        action="platform.runtime.desired_state.draft_created",
        entity_type="platform_config_version",
        entity_id=str(record.id),
        category="security",
        severity="info",
        after={"environment": environment, "revision": revision, "active": False, "digest": record.digest},
        metadata={"reason": payload.reason},
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="desired-state revision conflict") from exc
    return {"id": str(record.id), "environment": environment, "revision": revision,
            "digest": record.digest, "active": False}


class DesiredStateActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    change_id: UUID
    reason: str = Field(min_length=5, max_length=500)


@router.post("/desired-state/activate")
async def activate_verified_desired_state(
    payload: DesiredStateActivationRequest,
    principal: PlatformRuntimeManagePrincipal,
    session: DBSession,
) -> dict[str, object]:
    """Promote only an independently approved, reported-complete deployment.

    Fail closed on stale source revisions and unknown/unfinished executions.
    This updates the control-plane snapshot only; it never mutates AWS.
    """
    change = await session.get(PlatformChangeRecord, payload.change_id)
    if change is None:
        raise HTTPException(status_code=404, detail="platform change not found")
    if change.status != "completed" or change.approved_by is None:
        raise HTTPException(status_code=409, detail="change lacks approval and completed execution")
    if change.requested_by == principal.user_id:
        raise HTTPException(status_code=403, detail="change requestor cannot activate their own change")
    execution = await session.scalar(
        select(PlatformDeploymentExecution)
        .where(
            PlatformDeploymentExecution.change_id == change.id,
            PlatformDeploymentExecution.status == "completed",
            PlatformDeploymentExecution.source_digest == change.source_digest,
            PlatformDeploymentExecution.target_digest == change.target_digest,
        )
        .order_by(desc(PlatformDeploymentExecution.completed_at))
        .limit(1)
    )
    if execution is None:
        raise HTTPException(status_code=409, detail="matching completed deployment proof is missing")
    target = await session.scalar(
        select(PlatformConfigVersion)
        .where(
            PlatformConfigVersion.environment == change.environment,
            PlatformConfigVersion.revision == change.target_revision,
        )
        .with_for_update()
    )
    if target is None or target.digest != change.target_digest or target.active:
        raise HTTPException(status_code=409, detail="inactive target revision missing or mismatched")
    target_spec = PlatformSpec.model_validate(target.configuration_json)
    if (
        target_spec.metadata.environment != change.environment
        or target_spec.metadata.revision != target.revision
        or spec_digest(target_spec) != target.digest
    ):
        raise HTTPException(status_code=409, detail="target snapshot integrity mismatch")
    current = await session.scalar(
        select(PlatformConfigVersion)
        .where(
            PlatformConfigVersion.environment == change.environment,
            PlatformConfigVersion.active.is_(True),
        )
        .with_for_update()
    )
    if (
        current is None
        or current.revision != change.source_revision
        or current.digest != change.source_digest
    ):
        raise HTTPException(status_code=409, detail="stale or missing active source revision")
    current_spec = PlatformSpec.model_validate(current.configuration_json)
    if spec_digest(current_spec) != current.digest:
        raise HTTPException(status_code=409, detail="source snapshot integrity mismatch")
    if change.target_revision <= change.source_revision:
        raise HTTPException(status_code=409, detail="target revision must advance")
    # Conditional database writes are the concurrency boundary, not the earlier
    # SELECT snapshots. A second activator cannot reuse the same active source.
    retired = await session.execute(
        update(PlatformConfigVersion)
        .where(
            PlatformConfigVersion.id == current.id,
            PlatformConfigVersion.active.is_(True),
            PlatformConfigVersion.digest == change.source_digest,
        )
        .values(active=False)
    )
    if retired.rowcount != 1:
        raise HTTPException(status_code=409, detail="active source changed concurrently")
    promoted = await session.execute(
        update(PlatformConfigVersion)
        .where(
            PlatformConfigVersion.id == target.id,
            PlatformConfigVersion.active.is_(False),
            PlatformConfigVersion.digest == change.target_digest,
        )
        .values(active=True)
    )
    if promoted.rowcount != 1:
        await session.rollback()
        raise HTTPException(status_code=409, detail="target changed concurrently")
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        actor_user_id=principal.user_id,
        action="platform.runtime.desired_state.activated",
        entity_type="platform_config_version",
        entity_id=str(target.id),
        category="security",
        severity="warning",
        after={"environment": change.environment, "revision": target.revision,
               "digest": target.digest, "changeId": str(change.id)},
        metadata={"reason": payload.reason, "executionId": str(execution.id)},
    )
    await session.commit()
    return {"environment": change.environment, "revision": target.revision,
            "digest": target.digest, "active": True, "changeId": str(change.id)}


@router.get("/desired-state")
async def get_persisted_desired_state(
    _: PlatformSystemReadPrincipal,
    session: DBSession,
    environment: str = Query(min_length=1, max_length=32, pattern=r"^(development|test|staging|production)$"),
) -> dict[str, object]:
    """Read only an active, persisted desired-state revision.

    Never silently reconstruct production truth from local environment
    variables: absence of a persisted version is a distinct, auditable state.
    """
    record = await session.scalar(
        select(PlatformConfigVersion)
        .where(
            PlatformConfigVersion.environment == environment,
            PlatformConfigVersion.active.is_(True),
        )
        .order_by(desc(PlatformConfigVersion.revision))
        .limit(1)
    )
    if record is None:
        return {
            "environment": environment,
            "state": "unconfigured",
            "source": "database",
            "qualified": False,
            "desired": None,
        }
    spec = PlatformSpec.model_validate(record.configuration_json)
    if spec.metadata.environment != environment or spec.metadata.revision != record.revision:
        raise HTTPException(status_code=409, detail="persisted desired-state metadata mismatch")
    from northstar_api.modules.platform_runtime.control_plane import spec_digest
    if spec_digest(spec) != record.digest:
        raise HTTPException(status_code=409, detail="persisted desired-state integrity mismatch")
    return {
        "environment": environment,
        "state": "persisted",
        "source": "database",
        "qualified": False,
        "revision": record.revision,
        "digest": record.digest,
        "desired": spec.model_dump(mode="json"),
    }


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


@router.post("/changes", response_model=RuntimeChangeOut, status_code=status.HTTP_201_CREATED)
async def create_runtime_change(
    payload: RuntimeChangeCreateRequest,
    principal: PlatformRuntimeManagePrincipal,
    session: DBSession,
) -> RuntimeChangeOut:
    """Persist a reviewable change request; never execute infrastructure."""
    analysis = analyze_capability_change(payload.current, payload.desired)
    environment = payload.desired.metadata.environment
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
    gate = classify_transition(payload.current, payload.desired)
    # New non-noop requests always start in the review queue; do not dispatch
    # immediately from a draft configuration without independently checked
    # evidence, even when the older planner considers a change hot-safe.
    change_status: ChangeStatus = (
        "rejected"
        if analysis.plan.action == "reject"
        else "completed"
        if analysis.plan.action == "noop"
        else "waiting_approval"
        if analysis.plan.action != "noop"
        else "approved"
    )
    record = PlatformChangeRecord(
        id=analysis.plan.plan_id if analysis.plan.plan_id else uuid4(),
        environment=environment,
        requested_by=principal.user_id,
        status=change_status,
        action=analysis.plan.action,
        classification=analysis.plan.classification,
        requires_approval=analysis.plan.action != "noop",
        destructive=analysis.plan.destructive,
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
            "governanceClass": gate.change_class.value,
            "requiredEvidence": list(gate.required_evidence),
        },
        requested_at=now,
        current_spec_json=payload.current.model_dump(mode="json"),
        desired_spec_json=payload.desired.model_dump(mode="json"),
        approved_at=now if change_status in {"completed", "approved"} else None,
        completed_at=now if change_status == "completed" else None,
    )
    session.add(record)
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
    integrity_blockers = persisted_change_integrity_blockers(
        current_json=record.current_spec_json,
        desired_json=record.desired_spec_json,
        environment=record.environment,
        source_revision=record.source_revision,
        target_revision=record.target_revision,
        source_digest=record.source_digest,
        target_digest=record.target_digest,
        action=record.action,
        classification=record.classification,
    )
    if integrity_blockers:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "deployment_plan_integrity_failed", "blockers": integrity_blockers},
        )
    # Check the persisted immutable specs, never trust a client-provided class.
    # Approved work is not dispatched without qualified migration evidence.
    gate = classify_transition(
        PlatformSpec.model_validate(record.current_spec_json),
        PlatformSpec.model_validate(record.desired_spec_json),
    )
    if gate.change_class in {SwitchClass.L, SwitchClass.E}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="locked or unqualified change")
    # The signer runs outside this API. Without a separately provisioned key,
    # approval remains blocked. All required artifacts must be signed and
    # scoped to the precise environment and desired-state transition.
    key = os.environ.get("PLATFORM_QUALIFICATION_HMAC_KEY", "").encode("utf-8")
    blockers = verify_qualification_proofs(
        payload.evidence,
        required=gate.required_evidence,
        environment=record.environment,
        source_digest=record.source_digest,
        target_digest=record.target_digest,
        signing_key=key,
    )
    if blockers:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "deployment_evidence_required", "blockers": blockers},
        )
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
