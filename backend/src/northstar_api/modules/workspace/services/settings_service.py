"""Persist Workspace settings without changing the legacy storage pipeline.

Every operation receives a Workspace already authorized and locked by its API
handler. The caller retains validation, audit, outbox and transaction ownership.
"""

from __future__ import annotations

from typing import Any

from northstar_api.models import Workspace
from northstar_api.modules.workspace.contracts import (
    DeveloperSettings,
    GeneralSettings,
    NotificationSettings,
    SecuritySettings,
)
from northstar_api.modules.workspace.store import save_document, settings_document


def update_general_settings(workspace: Workspace, payload: GeneralSettings) -> dict[str, Any]:
    document = settings_document(workspace)
    before = document.general.model_dump(by_alias=True, mode="json")
    document.general = payload
    save_document(workspace, document)
    return before


def update_security_settings(workspace: Workspace, payload: SecuritySettings) -> dict[str, Any]:
    document = settings_document(workspace)
    before = document.security.model_dump(by_alias=True, mode="json")
    document.security = payload
    legacy = dict(workspace.settings_json or {})
    legacy["security"] = {
        "sensitiveDataMasking": payload.sensitive_data_masking,
        "securityContact": str(payload.security_contact) if payload.security_contact else None,
    }
    workspace.settings_json = legacy
    save_document(workspace, document)
    return before


def update_notification_settings(workspace: Workspace, payload: NotificationSettings) -> dict[str, Any]:
    document = settings_document(workspace)
    before = document.notifications.model_dump(by_alias=True, mode="json")
    document.notifications = payload
    save_document(workspace, document)
    return before


def update_developer_settings(workspace: Workspace, payload: DeveloperSettings) -> dict[str, Any]:
    document = settings_document(workspace)
    before = document.developer.model_dump(by_alias=True, mode="json")
    document.developer = payload
    save_document(workspace, document)
    return before
