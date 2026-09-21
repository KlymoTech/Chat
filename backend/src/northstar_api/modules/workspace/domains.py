from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError

from northstar_api.dependencies import DBSession, require_permissions
from northstar_api.entitlements import entitlement_for_plan
from northstar_api.models import Workspace, WorkspaceStatus
from northstar_api.modules.branding.repositories import persist_branding_document
from northstar_api.modules.branding.services.domain_service import TLS_ELIGIBLE_DOMAIN_STATUSES
from northstar_api.security import Principal
from northstar_api.workers.celery_app import celery_app

from .brand_cache import invalidate_brand_cache
from .contracts import DomainCreate, DomainRecord, WorkspaceSettingsBundle
from .domain_hostname import normalize_new_custom_domain_hostname
from .store import load_workspace, record_workspace_change, save_document, settings_document

router = APIRouter()
DomainManagePrincipal = Annotated[Principal, Depends(require_permissions("branding.domain.manage"))]
_MAX_WORKSPACE_DOMAINS = 20  # Match DomainsSettings.domains max_length.


def _interactive_only(principal: Principal) -> None:
    if principal.token_id.startswith("api_key:"):
        raise HTTPException(status_code=403, detail="Interactive branding domain management required")


def _enqueue(task_name: str, *, tenant_id: str, workspace_id: str, domain_id: str) -> bool:
    try:
        celery_app.send_task(
            task_name,
            args=[tenant_id, workspace_id, domain_id],
            queue="operations",
            routing_key="operations",
        )
    except Exception:  # broker/client failures vary by transport; persist an explicit retryable state
        return False
    return True


def _is_hostname_unique_violation(exc: IntegrityError) -> bool:
    """Recognize only the domain hostname constraint, not unrelated SQL errors."""
    orig = exc.orig
    diagnostic = getattr(orig, "diag", None)
    constraint = getattr(diagnostic, "constraint_name", None)
    if constraint == "uq_workspace_custom_domain_hostname":
        return True
    message = str(orig).lower()
    return (
        "uq_workspace_custom_domain_hostname" in message
        or "unique constraint failed: workspace_custom_domain.hostname" in message
    )


async def _mark_dispatch_failed(
    *,
    session: DBSession,
    principal: Principal,
    request: Request,
    workspace: Workspace,
    document: WorkspaceSettingsBundle,
    domain: DomainRecord,
    operation: str,
) -> None:
    # The initial request is committed before queue dispatch. Another request
    # may disable the domain, archive the workspace or restart verification
    # before the broker reports failure. Do not save the stale in-memory JSON.
    queued_status = "verifying" if operation == "verification" else "certificate_pending"
    domain_id = domain.id
    hostname = domain.hostname
    verification_name = domain.verification_name
    verification_value = domain.verification_value
    await session.refresh(
        workspace,
        attribute_names=["settings_json", "status"],
        with_for_update=True,
    )
    document = settings_document(workspace)
    current = next((item for item in document.domains.domains if item.id == domain_id), None)
    if (
        workspace.status != WorkspaceStatus.ACTIVE
        or current is None
        or current.hostname != hostname
        or current.status != queued_status
        or current.verification_name != verification_name
        or current.verification_value != verification_value
    ):
        # No change belongs to this failed request; release the row lock.
        await session.rollback()
        return
    domain = current
    domain.status = "failed"
    domain.failure_reason = "Background worker dispatch is unavailable; retry this operation"
    save_document(workspace, document)
    await persist_branding_document(session, workspace, document)
    record_workspace_change(
        session,
        principal,
        workspace,
        f"workspace.domain.{operation}.dispatch_failed",
        ["status", "failureReason"],
        resource_type="workspace_custom_domain",
        resource_id=domain.id,
        after={
            "hostname": domain.hostname,
            "status": domain.status,
            "failureReason": domain.failure_reason,
        },
        reason="Worker dispatch failed after durable request state was committed",
        request=request,
    )
    await session.commit()
    await invalidate_brand_cache(workspace.id, hostnames=[domain.hostname])


@router.post("/domains", response_model=DomainRecord, status_code=status.HTTP_201_CREATED)
async def create_domain(
    payload: DomainCreate,
    request: Request,
    principal: DomainManagePrincipal,
    session: DBSession,
) -> DomainRecord:
    _interactive_only(principal)
    tenant, workspace = await load_workspace(principal, session)
    if not entitlement_for_plan(tenant.plan).custom_domain_enabled:
        raise HTTPException(status_code=403, detail="Your plan does not include custom domains")
    document = settings_document(workspace)
    try:
        normalized = normalize_new_custom_domain_hostname(payload.hostname)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Disabled domain rows still reserve their hostname in normalized storage.
    # Never attempt to insert a second row for the same hostname.
    if any(item.hostname == normalized for item in document.domains.domains):
        raise HTTPException(status_code=409, detail="Domain is already configured")
    # Mutating a Pydantic list does not re-run its max_length validator. Without
    # this guard a 21st entry makes the entire saved bundle fail to deserialize.
    if len(document.domains.domains) >= _MAX_WORKSPACE_DOMAINS:
        raise HTTPException(status_code=409, detail="Workspace custom-domain limit reached")
    domain = DomainRecord(
        hostname=normalized,
        verification_name=f"_northstar-verify.{normalized}",
        verification_value=secrets.token_urlsafe(24),
    )
    document.domains.domains.append(domain)
    save_document(workspace, document)
    try:
        # The global unique constraint is authoritative even when tenant RLS
        # prevents this workspace from seeing a hostname claimed elsewhere.
        await persist_branding_document(session, workspace, document)
        record_workspace_change(
            session,
            principal,
            workspace,
            "workspace.domain.created",
            ["hostname", "status"],
            resource_type="workspace_custom_domain",
            resource_id=domain.id,
            after={"hostname": normalized, "status": domain.status},
            request=request,
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if _is_hostname_unique_violation(exc):
            raise HTTPException(status_code=409, detail="Domain is already configured") from None
        raise
    await invalidate_brand_cache(workspace.id, hostnames=[normalized])
    return domain


@router.post(
    "/domains/{domain_id}/verification-start",
    response_model=DomainRecord,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_domain_verification(
    domain_id: str,
    request: Request,
    principal: DomainManagePrincipal,
    session: DBSession,
) -> DomainRecord:
    _interactive_only(principal)
    _, workspace = await load_workspace(principal, session)
    document = settings_document(workspace)
    domain = next((item for item in document.domains.domains if item.id == domain_id), None)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    if domain.status in {"disabled", "active"}:
        raise HTTPException(status_code=409, detail="Domain cannot be verified in its current state")
    before = {"hostname": domain.hostname, "status": domain.status}
    domain.status = "verifying"
    domain.failure_reason = ""
    save_document(workspace, document)
    await persist_branding_document(session, workspace, document)
    record_workspace_change(
        session,
        principal,
        workspace,
        "workspace.domain.verification.queued",
        ["status"],
        resource_type="workspace_custom_domain",
        resource_id=domain.id,
        before=before,
        after={"hostname": domain.hostname, "status": domain.status},
        reason="Administrator requested DNS ownership verification",
        request=request,
    )
    await session.commit()
    await invalidate_brand_cache(workspace.id, hostnames=[domain.hostname])
    dispatched = _enqueue(
        "northstar.verify_workspace_brand_domain",
        tenant_id=str(workspace.tenant_id),
        workspace_id=str(workspace.id),
        domain_id=domain.id,
    )
    if not dispatched:
        await _mark_dispatch_failed(
            session=session,
            principal=principal,
            request=request,
            workspace=workspace,
            document=document,
            domain=domain,
            operation="verification",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Domain verification worker is unavailable; retry the verification request",
        )
    return domain


@router.post(
    "/domains/{domain_id}/activation-check",
    response_model=DomainRecord,
    status_code=status.HTTP_202_ACCEPTED,
)
async def check_domain_activation(
    domain_id: str,
    request: Request,
    principal: DomainManagePrincipal,
    session: DBSession,
) -> DomainRecord:
    _interactive_only(principal)
    _, workspace = await load_workspace(principal, session)
    document = settings_document(workspace)
    domain = next((item for item in document.domains.domains if item.id == domain_id), None)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    # "failed" is ambiguous: it may mean DNS ownership was never verified.
    # Require another successful DNS verification before a failed domain can
    # proceed to TLS validation; certificate_pending remains retryable.
    if domain.status not in TLS_ELIGIBLE_DOMAIN_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="Verify DNS ownership before checking activation",
        )
    before = {"hostname": domain.hostname, "status": domain.status}
    domain.status = "certificate_pending"
    domain.failure_reason = ""
    save_document(workspace, document)
    await persist_branding_document(session, workspace, document)
    record_workspace_change(
        session,
        principal,
        workspace,
        "workspace.domain.activation.queued",
        ["status"],
        resource_type="workspace_custom_domain",
        resource_id=domain.id,
        before=before,
        after={"hostname": domain.hostname, "status": domain.status},
        reason="Administrator requested TLS readiness validation",
        request=request,
    )
    await session.commit()
    await invalidate_brand_cache(workspace.id, hostnames=[domain.hostname])
    dispatched = _enqueue(
        "northstar.check_workspace_brand_tls",
        tenant_id=str(workspace.tenant_id),
        workspace_id=str(workspace.id),
        domain_id=domain.id,
    )
    if not dispatched:
        await _mark_dispatch_failed(
            session=session,
            principal=principal,
            request=request,
            workspace=workspace,
            document=document,
            domain=domain,
            operation="activation",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Domain activation worker is unavailable; retry the activation request",
        )
    return domain


@router.post("/domains/{domain_id}/disable", response_model=DomainRecord)
async def disable_domain(
    domain_id: str,
    request: Request,
    principal: DomainManagePrincipal,
    session: DBSession,
) -> DomainRecord:
    _interactive_only(principal)
    _, workspace = await load_workspace(principal, session)
    document = settings_document(workspace)
    domain = next((item for item in document.domains.domains if item.id == domain_id), None)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    before = {"hostname": domain.hostname, "status": domain.status}
    domain.status = "disabled"
    save_document(workspace, document)
    await persist_branding_document(session, workspace, document)
    record_workspace_change(
        session,
        principal,
        workspace,
        "workspace.domain.disabled",
        ["status"],
        resource_type="workspace_custom_domain",
        resource_id=domain.id,
        before=before,
        after={"hostname": domain.hostname, "status": domain.status},
        request=request,
    )
    await session.commit()
    await invalidate_brand_cache(workspace.id, hostnames=[domain.hostname])
    return domain
