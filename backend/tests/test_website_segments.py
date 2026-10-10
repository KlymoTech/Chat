"""Lead segment contract and missing-data behavior (Blueprint 46.3)."""
from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from northstar_api.lead_crm.website_segments import (
    SegmentRegister, WebsiteSegment, matches_segment,
)


def segment(**overrides) -> WebsiteSegment:
    return WebsiteSegment.model_validate({
        "id": str(uuid4()), "name": "Website enquiry leads", "enabled": True,
        "purpose": "operations", "logic": "all",
        "include": [
            {"field": "source_channel", "equals": " website_form "},
            {"field": "qualification_status", "equals": "Pending"},
        ],
        "exclude": [{"field": "utm_source", "equals": "test"}],
        **overrides,
    })


def test_and_or_rules_exclusions_and_unknown_input():
    scoped = segment()
    assert matches_segment(scoped, {
        "source_channel": "WEBSITE_FORM", "qualification_status": "pending",
        "utm_source": "google",
    }) == (True, False)
    assert matches_segment(scoped, {
        "source_channel": "website_form", "qualification_status": "pending",
        "utm_source": "test",
    }) == (False, False)
    assert matches_segment(scoped, {
        "source_channel": "website_form", "qualification_status": None,
        "utm_source": None,
    }) == (False, True)
    either = segment(logic="any")
    assert matches_segment(either, {
        "source_channel": "unknown", "qualification_status": "pending",
        "utm_source": "organic",
    }) == (True, False)


@pytest.mark.parametrize("include", [
    [{"field": "email", "equals": "user@example.com"}],
    [{"field": "ip_address", "equals": "1.2.3.4"}],
    [{"field": "utm_source", "equals": ""}],
    [
        {"field": "source_channel", "equals": "widget"},
        {"field": "source_channel", "equals": "WIDGET"},
    ],
])
def test_sensitive_invalid_and_duplicate_conditions_rejected(include):
    with pytest.raises(ValidationError):
        segment(include=include)


def test_duplicate_segment_ids_and_arbitrary_fields_rejected():
    one = segment()
    with pytest.raises(ValidationError):
        SegmentRegister(version=1, segments=(one, one))
    with pytest.raises(ValidationError):
        segment(purpose="profiling")
    with pytest.raises(ValidationError):
        segment(logic="sql")
    with pytest.raises(ValidationError):
        segment(include=[{"field": "name", "equals": "Alice"}])


def test_rules_are_bounded_and_read_only():
    with pytest.raises(ValidationError):
        segment(include=[{"field": "utm_source", "equals": str(i)} for i in range(7)])
    with pytest.raises(ValidationError):
        segment(extra="SELECT * FROM leads")
