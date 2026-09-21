"""Regression tests for preserving existing preferences during partial writes."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from northstar_api.modules.workspace.services.preference_merge import merge_workspace_preferences
from northstar_api.workspace_contract import WorkspacePreferences


def test_legacy_three_field_request_preserves_extended_profile() -> None:
    current = WorkspacePreferences(
        timezone="UTC", industry="Education", currency="INR", description="Keep me",
        business_hours={"monday": {"enabled": True, "opens": "08:00", "closes": "16:00"}},
    )
    requested = WorkspacePreferences.model_validate({
        "timezone": "Europe/London", "defaultLanguage": "French", "dateFormat": "YYYY-MM-DD",
    })
    merged = merge_workspace_preferences(current, requested)
    assert merged.timezone == "Europe/London"
    assert merged.default_language == "French"
    assert merged.date_format == "YYYY-MM-DD"
    assert merged.industry == "Education"
    assert merged.currency == "INR"
    assert merged.description == "Keep me"
    assert merged.business_hours.monday.opens == "08:00"
    assert merged.business_hours.monday.closes == "16:00"


def test_single_day_time_change_preserves_other_days_and_omitted_day_properties() -> None:
    current = WorkspacePreferences(business_hours={
        "monday": {"enabled": True, "opens": "08:00", "closes": "16:00"},
        "sunday": {"enabled": True, "opens": "10:00", "closes": "14:00"},
    })
    requested = WorkspacePreferences.model_validate({"businessHours": {"monday": {"opens": "09:00"}}})
    merged = merge_workspace_preferences(current, requested)
    assert merged.business_hours.monday.enabled
    assert merged.business_hours.monday.opens == "09:00"
    assert merged.business_hours.monday.closes == "16:00"
    assert merged.business_hours.sunday.enabled
    assert merged.business_hours.sunday.opens == "10:00"


def test_explicit_blank_can_clear_optional_industry_without_resetting_other_values() -> None:
    current = WorkspacePreferences(industry="Education", country="India")
    requested = WorkspacePreferences.model_validate({"industry": ""})
    merged = merge_workspace_preferences(current, requested)
    assert merged.industry == ""
    assert merged.country == "India"


def test_merging_revalidates_business_hours_against_stored_values() -> None:
    current = WorkspacePreferences(business_hours={
        "monday": {"enabled": True, "opens": "08:00", "closes": "16:00"},
    })
    requested = WorkspacePreferences.model_validate({"businessHours": {"monday": {"opens": "16:00"}}})
    with pytest.raises(ValidationError):
        merge_workspace_preferences(current, requested)
