"""Extended Workspace profile contracts and changed-field audit behavior."""
from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from northstar_api.modules.workspace.services.general_settings import changed_preference_fields
from northstar_api.workspace_contract import BusinessDay, WorkspacePreferences, safe_legacy_read


def test_legacy_defaults_are_backward_compatible() -> None:
    preferences = WorkspacePreferences(timezone="UTC", default_language="English")
    assert preferences.industry == ""
    assert preferences.currency == "USD"
    assert preferences.week_start == "monday"
    assert preferences.business_hours.monday.enabled
    assert not preferences.business_hours.sunday.enabled
    assert preferences.model_dump(by_alias=True)["timeFormat"] == "24h"


def test_extended_profile_round_trips_in_existing_preferences_contract() -> None:
    original = WorkspacePreferences(
        timezone="UTC", industry="  Education  ", country="  India  ",
        description="  Classroom support  ", currency="INR", time_format="12h",
        week_start="sunday", workspace_icon="🎓",
        business_hours={"monday": {"enabled": True, "opens": "22:00", "closes": "06:00"}},
    )
    stored = original.model_dump(by_alias=True, mode="json")
    assert stored["industry"] == "Education"
    assert stored["businessHours"]["monday"] == {
        "enabled": True, "opens": "22:00", "closes": "06:00",
    }
    assert WorkspacePreferences.model_validate(stored) == original


@pytest.mark.parametrize("field,value", [
    ("currency", "INR!"), ("currency", "usd"),
    ("weekStart", "friday"), ("timeFormat", "25h"),
    ("workspaceIcon", "too-many-characters"),
    ("businessHours", {"monday": {"enabled": True, "opens": "invalid"}}),
    ("businessHours", {"monday": {"enabled": True, "opens": "09:00", "closes": "09:00"}}),
])
def test_invalid_general_settings_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        WorkspacePreferences.model_validate({field: value})


def test_disabled_day_can_have_default_equal_hours_until_reenabled() -> None:
    assert BusinessDay(enabled=False, opens="09:00", closes="09:00").enabled is False
    with pytest.raises(ValidationError):
        BusinessDay(enabled=True, opens="09:00", closes="09:00")


def test_legacy_corrupt_business_hours_fall_back_without_mutating_source() -> None:
    stored = {"timezone": "UTC", "industry": "Education", "businessHours": {"monday": {"opens": "oops"}}}
    original = deepcopy(stored)
    warnings: list[str] = []
    parsed = safe_legacy_read(WorkspacePreferences, stored, warnings)
    assert stored == original
    assert parsed.industry == "Education"
    assert parsed.business_hours.monday.opens == "09:00"
    assert len(warnings) == 1


def test_preference_audit_exposes_only_changed_field_names() -> None:
    before = WorkspacePreferences().model_dump(by_alias=True, mode="json")
    after = WorkspacePreferences(
        industry="Confidential industry", description="Private customer description",
        business_hours={"sunday": {"enabled": True, "opens": "10:00", "closes": "14:00"}},
    ).model_dump(by_alias=True, mode="json")
    assert changed_preference_fields(before, after) == (
        "business_hours", "description", "industry",
    )
    assert changed_preference_fields(after, after) == ()
