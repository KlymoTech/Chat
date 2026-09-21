"""Backward-compatible partial updates for workspace preferences.

Pydantic fills defaults for omitted fields during request validation. Applying a
fully dumped request would therefore erase newer preferences saved by another
client. Merge only explicitly provided values, including nested day fields.
"""
from __future__ import annotations

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
    return WorkspacePreferences.model_validate({**existing, **patch})
