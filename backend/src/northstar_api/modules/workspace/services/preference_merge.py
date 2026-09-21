"""Backward-compatible partial updates for workspace preferences.

Pydantic fills defaults for omitted fields during request validation. Applying a
fully dumped request would therefore erase newer preferences saved by another
client. Merge only explicitly provided values, including nested day fields.
"""
from __future__ import annotations

from fastapi import HTTPException
from pydantic import ValidationError

from northstar_api.workspace_contract import WorkspacePreferences


def merge_workspace_preferences(
    current: WorkspacePreferences, requested: WorkspacePreferences,
) -> WorkspacePreferences:
    existing = current.model_dump(by_alias=True, mode="json")
    patch = requested.model_dump(by_alias=True, mode="json", exclude_unset=True)
    if "businessHours" in patch:
        previous_hours = existing["businessHours"]
        patch["businessHours"] = {
            **previous_hours,
            **{
                day: {**previous_hours[day], **values}
                for day, values in patch["businessHours"].items()
            },
        }
    try:
        return WorkspacePreferences.model_validate({**existing, **patch})
    except ValidationError as exc:
        # The incoming fragment may be valid by itself but conflict with stored
        # day fields. Do not let that validation failure escape as HTTP 500 or
        # include customers' stored preference values in an error response.
        raise HTTPException(
            status_code=422,
            detail="Workspace preferences conflict with existing settings; review your changes",
        ) from exc
