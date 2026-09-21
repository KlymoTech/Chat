from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from northstar_api.dependencies import DBSession, require_permissions
from northstar_api.entitlements import entitlement_for_plan
from northstar_api.modules.branding.repositories import persist_branding_document
from northstar_api.security import Principal
from northstar_api.workers.celery_app import celery_app

from .brand_cache import invalidate_brand_cache
from .contracts import DomainCreate, DomainRecord
from .store import load_workspace, record_workspace_change, save_document, settings_document

router = APIRouter()
DomainManagePrincipal = Annotated[Principal, Depends(require_permissions("branding.domain.manage"))]


def _interactive_only(principal: Principal) -> None:
    if principal.token_id.startswith("api_key:"):
        raise HTTPException(status_code=403, detail="Interactive branding domain management required")


def _enqueue(task_name: str, *, tenant_id: str, workspace_id: str, domain_id: str) -> None:
    celery_app.send_task(
        task_name,
        args=[tenant_id, workspace_id, domain_id],
        queue="operations",
        routing_key="operations",
    )


@router.post("/domains", response_model=DomainRecord, status_code=201)
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
    normalized = DomainRecord.normalized_hostname(payload.hostname)
    if any(
        item.hostname == normalized and item.status != "disabled"
        for item in document.domains.domains
    ):
        raise HTTPException(status_code=409, detail="Domain is already configured")
    domain = DomainRecord(
        hostname=normalized,
        verification_name=f"_northstar-verify.{normalized}",
        verification_value=secrets.token_urlsafe(24),
    )
    document.domains.domains.append(domain)
    save_document(workspace, document)
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
    await invalidate_brand_cache(workspace.id, hostnames=[normalized])
    return domain


@router.post("/domains/{domain_id}/verification-start", response_model=DomainRecord)
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
    _enqueue(
        "northstar.verify_workspace_brand_domain",
        tenant_id=str(workspace.tenant_id),
        workspace_id=str(workspace.id),
        domain_id=domain.id,
    )
    return domain


@router.post("/domains/{domain_id}/activation-check", response_model=DomainRecord)
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
    if domain.status not in {"verified", "certificate_pending", "failed"}:
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
    _enqueue(
        "northstar.check_workspace_brand_tls",
        tenant_id=str(workspace.tenant_id),
        workspace_id=str(workspace.id),
        domain_id=domain.id,
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
