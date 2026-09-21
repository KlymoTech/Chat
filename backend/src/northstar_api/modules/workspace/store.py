from __future__ import annotations

from typing import Any

from northstar_api.dependencies import DBSession
from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.models import Workspace
from northstar_api.routers.workspace import _load_workspace
from northstar_api.security import Principal
from northstar_api.services.outbox import enqueue_event
from northstar_api.workspace_contract import WhiteLabelWrite

from .contracts import ExtendedBranding, WorkspaceSettingsBundle


async def load_workspace(principal: Principal, session: DBSession) -> tuple[Any, Workspace]:
    tenant, workspace, _, _ = await _load_workspace(
        principal.tenant_id,
        principal.workspace_id,
        principal.user_id,
        session,
    )
    return tenant, workspace


def settings_document(workspace: Workspace) -> WorkspaceSettingsBundle:
    raw = dict(workspace.settings_json or {}).get("workspaceSettingsV2", {})
    try:
        document = WorkspaceSettingsBundle.model_validate(raw)
    except (TypeError, ValueError):
        document = WorkspaceSettingsBundle()

    legacy_security = dict(workspace.settings_json or {}).get("security", {})
    if legacy_security:
        document.security.sensitive_data_masking = bool(
            legacy_security.get("sensitiveDataMasking", document.security.sensitive_data_masking)
        )
        document.security.security_contact = legacy_security.get(
            "securityContact", document.security.security_contact
        )

    if workspace.branding_json and document.branding_published is None:
        legacy = {
            key: value
            for key, value in workspace.branding_json.items()
            if key not in {"customDomain", "dnsStatus"}
        }
        try:
            identity = WhiteLabelWrite.model_validate(legacy)
        except (TypeError, ValueError):
            identity = None
        if identity is not None:
            document.branding_published = ExtendedBranding(identity=identity)
            document.branding_draft = document.branding_published.model_copy(deep=True)
    return document


def save_document(workspace: Workspace, document: WorkspaceSettingsBundle) -> None:
    settings = dict(workspace.settings_json or {})
    settings["workspaceSettingsV2"] = document.model_dump(by_alias=True, mode="json")
    workspace.settings_json = settings


def record_workspace_change(
    session: DBSession,
    principal: Principal,
    workspace: Workspace,
    action: str,
    fields: list[str] | None = None,
) -> None:
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace.id,
        actor_user_id=principal.user_id,
        action=action,
        entity_type="workspace",
        entity_id=str(workspace.id),
        category="workspace",
        metadata={"fields": fields or []},
    )
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="workspace",
        aggregate_id=workspace.id,
        event_type=f"{action}.v1",
        payload={"workspaceId": str(workspace.id)},
    )
