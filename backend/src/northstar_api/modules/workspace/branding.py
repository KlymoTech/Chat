from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from northstar_api.dependencies import DBSession, require_permissions
from northstar_api.entitlements import entitlement_for_plan
from northstar_api.models import Workspace
from northstar_api.security import Principal

from .contracts import (
    BrandVersion,
    DomainCreate,
    DomainRecord,
    ExtendedBranding,
    PublishRequest,
    RollbackRequest,
    WorkspaceSettingsBundle,
)
from .store import load_workspace, record_workspace_change, save_document, settings_document

router = APIRouter()
BrandViewPrincipal = Annotated[Principal, Depends(require_permissions("branding.view"))]
BrandEditPrincipal = Annotated[Principal, Depends(require_permissions("branding.edit"))]
BrandPublishPrincipal = Annotated[Principal, Depends(require_permissions("branding.publish"))]
DomainManagePrincipal = Annotated[Principal, Depends(require_permissions("branding.domain.manage"))]


def _interactive_only(principal: Principal, operation: str) -> None:
    if principal.token_id.startswith("api_key:"):
        raise HTTPException(status_code=403, detail=f"Interactive branding {operation} required")


def _check_brand_entitlements(plan: str, branding: ExtendedBranding) -> None:
    entitlement = entitlement_for_plan(plan)
    if not entitlement.white_label_enabled:
        raise HTTPException(status_code=403, detail="Your plan does not include white label")
    if branding.identity.branded_emails and not entitlement.branded_email_enabled:
        raise HTTPException(status_code=403, detail="Your plan does not include branded email")
    if branding.identity.remove_platform_branding and not entitlement.remove_platform_mark_enabled:
        raise HTTPException(status_code=403, detail="Your plan does not include platform-brand removal")


async def _publish(
    document: WorkspaceSettingsBundle,
    principal: Principal,
    session: DBSession,
    workspace: Workspace,
    plan: str,
    change_note: str,
) -> BrandVersion:
    _check_brand_entitlements(plan, document.branding_draft)
    version_number = max((item.version for item in document.branding_versions), default=0) + 1
    version = BrandVersion(
        version=version_number,
        created_by=str(principal.user_id),
        published_at=datetime.now(UTC),
        change_note=change_note,
        branding=document.branding_draft.model_copy(deep=True),
    )
    document.branding_published = version.branding.model_copy(deep=True)
    document.branding_versions = (document.branding_versions + [version])[-50:]
    active_domain = next(
        (item.hostname for item in document.domains.domains if item.status == "active"),
        "",
    )
    workspace.branding_json = {
        **version.branding.identity.model_dump(by_alias=True, mode="json"),
        "customDomain": active_domain,
        "dnsStatus": "verified" if active_domain else "not-configured",
    }
    save_document(workspace, document)
    record_workspace_change(
        session,
        principal,
        workspace,
        "workspace.brand.published",
        [f"version:{version_number}"],
    )
    await session.commit()
    return version


@router.get("/branding", response_model=WorkspaceSettingsBundle)
async def get_branding(
    principal: BrandViewPrincipal,
    session: DBSession,
) -> WorkspaceSettingsBundle:
    _, workspace = await load_workspace(principal, session)
    return settings_document(workspace)


@router.patch("/branding/draft", response_model=ExtendedBranding)
async def save_branding_draft(
    payload: ExtendedBranding,
    principal: BrandEditPrincipal,
    session: DBSession,
) -> ExtendedBranding:
    _interactive_only(principal, "editing")
    _, workspace = await load_workspace(principal, session)
    document = settings_document(workspace)
    document.branding_draft = payload
    save_document(workspace, document)
    record_workspace_change(
        session,
        principal,
        workspace,
        "workspace.brand.draft.updated",
        ["brandingDraft"],
    )
    await session.commit()
    return payload


@router.post("/branding/publish", response_model=BrandVersion)
async def publish_branding(
    payload: PublishRequest,
    principal: BrandPublishPrincipal,
    session: DBSession,
) -> BrandVersion:
    _interactive_only(principal, "publication")
    tenant, workspace = await load_workspace(principal, session)
    document = settings_document(workspace)
    return await _publish(document, principal, session, workspace, tenant.plan, payload.change_note)


@router.post("/branding/rollback", response_model=BrandVersion)
async def rollback_branding(
    payload: RollbackRequest,
    principal: BrandPublishPrincipal,
    session: DBSession,
) -> BrandVersion:
    _interactive_only(principal, "publication")
    tenant, workspace = await load_workspace(principal, session)
    document = settings_document(workspace)
    source = next(
        (item for item in document.branding_versions if item.version == payload.version),
        None,
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Brand version not found")
    document.branding_draft = source.branding.model_copy(deep=True)
    return await _publish(document, principal, session, workspace, tenant.plan, payload.change_note)


@router.post("/domains", response_model=DomainRecord, status_code=201)
async def create_domain(
    payload: DomainCreate,
    principal: DomainManagePrincipal,
    session: DBSession,
) -> DomainRecord:
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
    record_workspace_change(session, principal, workspace, "workspace.domain.created", [normalized])
    await session.commit()
    return domain


@router.post("/domains/{domain_id}/verification-start", response_model=DomainRecord)
async def start_domain_verification(
    domain_id: str,
    principal: DomainManagePrincipal,
    session: DBSession,
) -> DomainRecord:
    _, workspace = await load_workspace(principal, session)
    document = settings_document(workspace)
    domain = next((item for item in document.domains.domains if item.id == domain_id), None)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    if domain.status in {"disabled", "active"}:
        raise HTTPException(status_code=409, detail="Domain cannot be verified in its current state")
    domain.status = "verifying"
    domain.failure_reason = ""
    save_document(workspace, document)
    record_workspace_change(
        session,
        principal,
        workspace,
        "workspace.domain.verification.started",
        [domain.hostname],
    )
    await session.commit()
    return domain


@router.post("/domains/{domain_id}/disable", response_model=DomainRecord)
async def disable_domain(
    domain_id: str,
    principal: DomainManagePrincipal,
    session: DBSession,
) -> DomainRecord:
    _, workspace = await load_workspace(principal, session)
    document = settings_document(workspace)
    domain = next((item for item in document.domains.domains if item.id == domain_id), None)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    domain.status = "disabled"
    save_document(workspace, document)
    record_workspace_change(
        session,
        principal,
        workspace,
        "workspace.domain.disabled",
        [domain.hostname],
    )
    await session.commit()
    return domain
