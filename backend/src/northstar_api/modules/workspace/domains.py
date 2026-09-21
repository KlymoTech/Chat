from __future__ import annotations

import asyncio
import ipaddress
import secrets
import socket
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException

from northstar_api.config import get_settings
from northstar_api.dependencies import DBSession, require_permissions
from northstar_api.entitlements import entitlement_for_plan
from northstar_api.security import Principal

from .brand_cache import invalidate_brand_cache
from .contracts import DomainCreate, DomainRecord
from .store import load_workspace, record_workspace_change, save_document, settings_document

router = APIRouter()
DomainManagePrincipal = Annotated[Principal, Depends(require_permissions("branding.domain.manage"))]


def _interactive_only(principal: Principal) -> None:
    if principal.token_id.startswith("api_key:"):
        raise HTTPException(status_code=403, detail="Interactive branding domain management required")


async def _dns_json(name: str, record_type: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=6.0, follow_redirects=False) as client:
            response = await client.get(
                "https://dns.google/resolve",
                params={"name": name, "type": record_type},
                headers={"Accept": "application/dns-json"},
            )
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {}
    except (httpx.HTTPError, ValueError):
        return {}


async def _txt_verified(domain: DomainRecord) -> bool:
    payload = await _dns_json(domain.verification_name, "TXT")
    answers = payload.get("Answer", [])
    if not isinstance(answers, list):
        return False
    expected = domain.verification_value
    for answer in answers:
        if not isinstance(answer, dict):
            continue
        value = str(answer.get("data", "")).strip().strip('"').replace('" "', "")
        if value == expected:
            return True
    return False


async def _hostname_is_public(hostname: str) -> bool:
    def resolve() -> list[str]:
        try:
            return sorted(
                {
                    item[4][0]
                    for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
                }
            )
        except OSError:
            return []

    addresses = await asyncio.to_thread(resolve)
    if not addresses:
        return False
    for value in addresses:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            return False
        if not address.is_global:
            return False
    return True


async def _tls_ready(hostname: str) -> tuple[bool, str]:
    if not await _hostname_is_public(hostname):
        return False, "Domain does not currently resolve only to public addresses"
    path = get_settings().app_api_prefix.rstrip("/") + "/branding/health"
    try:
        async with httpx.AsyncClient(timeout=7.0, follow_redirects=False) as client:
            response = await client.get(f"https://{hostname}{path}")
        if response.status_code == 204:
            return True, ""
        return False, f"HTTPS health endpoint returned {response.status_code}"
    except httpx.HTTPError as exc:
        return False, f"TLS/HTTPS is not ready ({type(exc).__name__})"


@router.post("/domains", response_model=DomainRecord, status_code=201)
async def create_domain(
    payload: DomainCreate,
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
    record_workspace_change(
        session,
        principal,
        workspace,
        "workspace.domain.created",
        [normalized],
    )
    await session.commit()
    await invalidate_brand_cache(workspace.id, hostnames=[normalized])
    return domain


@router.post("/domains/{domain_id}/verification-start", response_model=DomainRecord)
async def start_domain_verification(
    domain_id: str,
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
    domain.status = "verifying"
    domain.failure_reason = ""
    if not await _txt_verified(domain):
        domain.status = "dns_pending"
        domain.failure_reason = (
            f"TXT record {domain.verification_name} does not yet match the verification token"
        )
        event = "workspace.domain.verification.pending"
    else:
        domain.status = "verified"
        event = "workspace.domain.verified"
    save_document(workspace, document)
    record_workspace_change(session, principal, workspace, event, [domain.hostname])
    await session.commit()
    await invalidate_brand_cache(workspace.id, hostnames=[domain.hostname])
    return domain


@router.post("/domains/{domain_id}/activation-check", response_model=DomainRecord)
async def check_domain_activation(
    domain_id: str,
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
    domain.status = "certificate_pending"
    ready, reason = await _tls_ready(domain.hostname)
    if ready:
        domain.status = "active"
        domain.failure_reason = ""
        action = "workspace.domain.activated"
    else:
        domain.failure_reason = reason
        action = "workspace.domain.certificate.pending"
    save_document(workspace, document)
    record_workspace_change(session, principal, workspace, action, [domain.hostname])
    await session.commit()
    await invalidate_brand_cache(workspace.id, hostnames=[domain.hostname])
    return domain


@router.post("/domains/{domain_id}/disable", response_model=DomainRecord)
async def disable_domain(
    domain_id: str,
    principal: DomainManagePrincipal,
    session: DBSession,
) -> DomainRecord:
    _interactive_only(principal)
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
    await invalidate_brand_cache(workspace.id, hostnames=[domain.hostname])
    return domain
