"""Persist validated Workspace teams through the original settings document.

The caller owns tenant authorization, the Workspace write lock, membership and
agent validation, audit/outbox and commit. This creates no new ORM mapping.
"""

from __future__ import annotations

from typing import Any

from northstar_api.models import Workspace
from northstar_api.modules.workspace.contracts import TeamsSettings
from northstar_api.modules.workspace.security_policy import validate_business_timezone
from northstar_api.modules.workspace.store import save_document, settings_document


def update_workspace_teams(workspace: Workspace, payload: TeamsSettings) -> dict[str, Any]:
    """Update only teams, preserving roles and unrelated Workspace settings."""
    # Keep internal service callers consistent with the existing HTTP boundary.
    # Validate all timezones before making any changes to the shared document.
    for team in payload.teams:
        validate_business_timezone(team.business_hours.timezone)
    document = settings_document(workspace)
    before = document.teams.model_dump(by_alias=True, mode="json")
    document.teams = payload
    save_document(workspace, document)
    return before
