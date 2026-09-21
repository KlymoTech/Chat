from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from northstar_api.access_policy import WORKSPACE_GRANTS, WORKSPACE_PERMISSIONS
from northstar_api.dependencies import DBSession, require_permissions
from northstar_api.security import Principal

from .contracts import (
    DeveloperSettings,
    GeneralSettings,
    NotificationSettings,
    SecuritySettings,
    WorkspaceSettingsBundle,
)
from .security_policy import normalize_trusted_domains, validate_business_timezone, validate_security_settings
from .store import load_workspace, record_workspace_change, save_document, settings_document

router = APIRouter()
SettingsViewPrincipal = Annotated[Principal, Depends(require_permissions("settings.view"))]
SettingsManagePrincipal = Annotated[Principal, Depends(require_permissions("settings.manage"))]


@router.get("", response_model=WorkspaceSettingsBundle)
async def get_settings(principal: SettingsViewPrincipal, session: DBSession) -> WorkspaceSettingsBundle:
    _, workspace = await load_workspace(principal, session)
    return settings_document(workspace)


@router.get("/capabilities")
async def get_capabilities(principal: SettingsViewPrincipal) -> dict[str, Any]:
    _ = principal
    return {
        "permissions": sorted(WORKSPACE_PERMISSIONS),
        "builtinRoles": {name: sorted(values) for name, values in WORKSPACE_GRANTS.items()},
        "resourceKinds": [
            "agents",
            "knowledge",
            "conversations",
            "courses",
            "batches",
            "students",
            "leads",
            "channels",
            "crm",
        ],
    }


@router.patch("/general", response_model=GeneralSettings)
async def update_general(
    payload: GeneralSettings,
    principal: SettingsManagePrincipal,
    session: DBSession,
) -> GeneralSettings:
    _, workspace = await load_workspace(principal, session)
    validate_business_timezone(payload.business_hours.timezone)
    document = settings_document(workspace)
    document.general = payload
    save_document(workspace, document)
    record_workspace_change(
        session,
        principal,
        workspace,
        "workspace.settings.general.updated",
        sorted(payload.model_fields_set),
    )
    await session.commit()
    return payload


@router.patch("/security", response_model=SecuritySettings)
async def update_security(
    payload: SecuritySettings,
    principal: SettingsManagePrincipal,
    session: DBSession,
) -> SecuritySettings:
    validate_security_settings(payload)
    payload = normalize_trusted_domains(payload)
    _, workspace = await load_workspace(principal, session)
    document = settings_document(workspace)
    document.security = payload
    legacy = dict(workspace.settings_json or {})
    legacy["security"] = {
        "sensitiveDataMasking": payload.sensitive_data_masking,
        "securityContact": str(payload.security_contact) if payload.security_contact else None,
    }
    workspace.settings_json = legacy
    save_document(workspace, document)
    record_workspace_change(
        session,
        principal,
        workspace,
        "workspace.settings.security.updated",
        sorted(payload.model_fields_set),
    )
    await session.commit()
    return payload


@router.patch("/notifications", response_model=NotificationSettings)
async def update_notifications(
    payload: NotificationSettings,
    principal: SettingsManagePrincipal,
    session: DBSession,
) -> NotificationSettings:
    _, workspace = await load_workspace(principal, session)
    document = settings_document(workspace)
    document.notifications = payload
    save_document(workspace, document)
    record_workspace_change(
        session,
        principal,
        workspace,
        "workspace.settings.notifications.updated",
        sorted(payload.model_fields_set),
    )
    await session.commit()
    return payload


@router.patch("/developer", response_model=DeveloperSettings)
async def update_developer(
    payload: DeveloperSettings,
    principal: SettingsManagePrincipal,
    session: DBSession,
) -> DeveloperSettings:
    _, workspace = await load_workspace(principal, session)
    document = settings_document(workspace)
    document.developer = payload
    save_document(workspace, document)
    record_workspace_change(
        session,
        principal,
        workspace,
        "workspace.settings.developer.updated",
        sorted(payload.model_fields_set),
    )
    await session.commit()
    return payload
