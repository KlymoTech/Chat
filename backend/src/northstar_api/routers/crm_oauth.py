from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session, set_tenant_context
from northstar_api.dependencies import AdminPrincipal
from northstar_api.lead_crm.connectors import CRMConnectionContext, CRMError, crm_registry
from northstar_api.lead_crm.credentials import CredentialStoreError, credential_store
from northstar_api.lead_crm.domain import CRMConnectionStatus, CRMProvider
from northstar_api.lead_crm.models import CRMConnection
from northstar_api.lead_crm.oauth import OAuthStateError, oauth_state_store

router = APIRouter(prefix="/crm", tags=["crm-oauth"])
DB = Annotated[AsyncSession, Depends(get_session)]


def _decrypt_credentials(connection: CRMConnection) -> dict[str, Any]:
    if not connection.credentials_encrypted:
        return {}
    try:
        return credential_store.decrypt(connection.credentials_encrypted)
    except CredentialStoreError as exc:
        raise HTTPException(status_code=409, detail="CRM credentials require reconnection") from exc


def _redirect_uri(request: Request, connection: CRMConnection) -> str:
    configured = str((connection.configuration_json or {}).get("oauthRedirectUri") or "").strip()
    if configured:
        if request.url.scheme == "https" and not configured.startswith("https://"):
            raise HTTPException(status_code=400, detail="OAuth redirect URI must use HTTPS")
        return configured
    return str(request.url_for("crm_oauth_callback", provider=connection.provider))


async def _start_oauth(
    connection_id: UUID,
    request: Request,
    principal: AdminPrincipal,
    session: AsyncSession,
) -> dict[str, Any]:
    connection = await session.scalar(
        select(CRMConnection).where(
            CRMConnection.id == connection_id,
            CRMConnection.tenant_id == principal.tenant_id,
        )
    )
    if not connection:
        raise HTTPException(status_code=404, detail="CRM connection not found")
    try:
        provider = CRMProvider(connection.provider)
        connector = crm_registry.get(provider)
    except (ValueError, CRMError) as exc:
        raise HTTPException(status_code=409, detail="CRM connector is unavailable") from exc
    if not connector.capabilities.oauth:
        raise HTTPException(status_code=400, detail="This CRM connection does not use OAuth")

    credentials = _decrypt_credentials(connection)
    redirect_uri = _redirect_uri(request, connection)
    try:
        state = await oauth_state_store.create(
            tenant_id=principal.tenant_id,
            connection_id=connection.id,
            user_id=principal.user_id,
            provider=provider.value,
            redirect_uri=redirect_uri,
        )
        context = CRMConnectionContext(
            tenant_id=principal.tenant_id,
            connection_id=connection.id,
            provider=provider,
            configuration=connection.configuration_json,
            credentials=credentials,
        )
        code_challenge = (
            state.code_challenge if bool(connection.configuration_json.get("pkce", False)) else None
        )
        authorization_url = connector.build_authorization_url(
            context,
            redirect_uri=redirect_uri,
            state=state.state,
            code_challenge=code_challenge,
        )
    except OAuthStateError as exc:
        raise HTTPException(status_code=503, detail="OAuth state service is unavailable") from exc
    except CRMError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    connection.status = CRMConnectionStatus.CONNECTING.value
    connection.last_error = None
    await session.commit()
    return {
        "authorizationUrl": authorization_url,
        "expiresIn": oauth_state_store.ttl_seconds,
        "connectionId": str(connection.id),
        "provider": provider.value,
    }


@router.post("/connections/{connection_id}/oauth/start")
async def start_crm_oauth(
    connection_id: UUID,
    request: Request,
    principal: AdminPrincipal,
    session: DB,
) -> dict[str, Any]:
    return await _start_oauth(connection_id, request, principal, session)


@router.post("/connections/{connection_id}/reconnect")
async def reconnect_crm(
    connection_id: UUID,
    request: Request,
    principal: AdminPrincipal,
    session: DB,
) -> dict[str, Any]:
    return await _start_oauth(connection_id, request, principal, session)


@router.get("/oauth/{provider}/callback", name="crm_oauth_callback")
async def crm_oauth_callback(
    provider: str,
    session: DB,
    state: str = Query(min_length=20, max_length=512),
    code: str | None = Query(default=None, min_length=1, max_length=4096),
    error: str | None = Query(default=None, max_length=512),
) -> dict[str, Any]:
    try:
        saved = await oauth_state_store.consume(state)
    except OAuthStateError as exc:
        raise HTTPException(
            status_code=400, detail="OAuth state is invalid, expired, or already used"
        ) from exc
    if saved.provider != provider:
        raise HTTPException(status_code=400, detail="OAuth provider does not match the authorization state")

    await set_tenant_context(session, saved.tenant_id)
    connection = await session.scalar(
        select(CRMConnection).where(
            CRMConnection.id == saved.connection_id,
            CRMConnection.tenant_id == saved.tenant_id,
            CRMConnection.provider == provider,
        )
    )
    if not connection:
        raise HTTPException(status_code=404, detail="CRM connection no longer exists")
    if error or not code:
        connection.status = CRMConnectionStatus.AUTH_REQUIRED.value
        connection.last_failure_at = datetime.now(UTC)
        connection.last_error = f"OAuth authorization failed: {error or 'missing_code'}"[:1000]
        await session.commit()
        raise HTTPException(status_code=400, detail="CRM authorization was not completed")

    try:
        provider_enum = CRMProvider(provider)
        connector = crm_registry.get(provider_enum)
        existing = _decrypt_credentials(connection)
        context = CRMConnectionContext(
            tenant_id=saved.tenant_id,
            connection_id=connection.id,
            provider=provider_enum,
            configuration=connection.configuration_json,
            credentials=existing,
        )
        updated = await connector.exchange_authorization_code(
            context,
            code=code,
            redirect_uri=saved.redirect_uri,
            code_verifier=saved.code_verifier
            if bool(connection.configuration_json.get("pkce", False))
            else None,
        )
        connection.credentials_encrypted = credential_store.encrypt(updated)
        connection.last_authenticated_at = datetime.now(UTC)
        health = await connector.health_check(
            CRMConnectionContext(
                tenant_id=saved.tenant_id,
                connection_id=connection.id,
                provider=provider_enum,
                configuration=connection.configuration_json,
                credentials=updated,
            )
        )
        connection.status = health.status.value
        connection.last_health_at = datetime.now(UTC)
        connection.last_error = (
            None
            if health.status.value == CRMConnectionStatus.HEALTHY.value
            else str(health.details.get("error") or "Health validation failed")[:1000]
        )
        if health.status.value == CRMConnectionStatus.HEALTHY.value:
            connection.last_success_at = datetime.now(UTC)
        else:
            connection.last_failure_at = datetime.now(UTC)
        await session.commit()
    except (CRMError, CredentialStoreError, ValueError) as exc:
        connection.status = CRMConnectionStatus.AUTH_REQUIRED.value
        connection.last_failure_at = datetime.now(UTC)
        connection.last_error = "OAuth token exchange or validation failed"
        await session.commit()
        raise HTTPException(status_code=409, detail="CRM authorization could not be completed") from exc

    return {
        "connected": connection.status == CRMConnectionStatus.HEALTHY.value,
        "connectionId": str(connection.id),
        "provider": connection.provider,
        "status": connection.status,
    }
