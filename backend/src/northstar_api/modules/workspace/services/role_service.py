"""Workspace custom-role lifecycle rules for the existing settings document.

The caller has already authorized the tenant/workspace and locked the current
Workspace row. This service does not create mappings or own a transaction.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from northstar_api.models import Workspace
from northstar_api.modules.workspace.contracts import RolesSettings, TeamsSettings
from northstar_api.modules.workspace.store import save_document, settings_document


def ensure_role_removal_safe(
    current_roles: RolesSettings,
    requested_roles: RolesSettings,
    current_teams: TeamsSettings,
) -> None:
    """Prevent removal of a role that is still assigned to an existing team.

    Only *removed* role IDs are checked: historical unrelated team references
    must not block an otherwise compatible role update.
    """
    removed_ids = (
        {role.id for role in current_roles.custom_roles}
        - {role.id for role in requested_roles.custom_roles}
    )
    if not removed_ids:
        return
    for team in current_teams.teams:
        if removed_ids.intersection(team.role_ids):
            raise HTTPException(
                status_code=409,
                detail=f"Remove the role assignment from team {team.name} before deleting its role",
            )


def update_workspace_roles(workspace: Workspace, payload: RolesSettings) -> dict[str, Any]:
    """Persist role settings using the established JSON compatibility path."""
    document = settings_document(workspace)
    ensure_role_removal_safe(document.roles, payload, document.teams)
    before = document.roles.model_dump(by_alias=True, mode="json")
    document.roles = payload
    save_document(workspace, document)
    return before
