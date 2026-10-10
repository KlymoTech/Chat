"""Guarded internal-review automation contracts; no customer messages or new data stores."""
from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from northstar_api.lead_crm.website_internal_automations import (
    InternalAutomation,
    InternalAutomationExecute,
    InternalAutomationRegister,
    operationally_eligible,
)


def automation(**overrides) -> InternalAutomation:
    return InternalAutomation.model_validate({
        "id": str(uuid4()),
        "name": "Review new website leads",
        "segment_id": str(uuid4()),
        "enabled": True,
        "action": "notify_admins",
        "max_per_run": 25,
        **overrides,
    })


def test_only_allowlisted_review_action_and_bounded_run_size():
    value = automation()
    assert value.action == "notify_admins"
    assert value.max_per_run == 25
    assert value.name == "Review new website leads"
    for invalid in [
        {"action": "send_email"},
        {"action": "sync_to_crm"},
        {"action": "send_whatsapp"},
        {"max_per_run": 100},
        {"max_per_run": 0},
        {"name": "  "},
        {"extra": "not-allowed"},
    ]:
        with pytest.raises(ValidationError):
            automation(**invalid)


def test_duplicate_automation_ids_and_excessive_policies_are_denied():
    one = automation()
    with pytest.raises(ValidationError):
        InternalAutomationRegister(version=1, automations=(one, one))
    with pytest.raises(ValidationError):
        InternalAutomationRegister(version=1, automations=tuple(automation() for _ in range(13)))
    with pytest.raises(ValidationError):
        InternalAutomationExecute(
            expected_policy_version=0,
            expected_segment_version=1,
            expected_eligible_leads=1,
        )
    with pytest.raises(ValidationError):
        InternalAutomationExecute(
            expected_policy_version=1,
            expected_segment_version=1,
            expected_eligible_leads=501,
        )


@pytest.mark.parametrize(("lead_status", "consent", "processing", "expected"), [
    ("new", True, "granted", True),
    ("contacted", True, "consented", True),
    ("new", False, "granted", False),
    ("new", True, None, False),
    ("new", True, "withdrawn", False),
    ("new", True, "revoked", False),
    ("archived", True, "granted", False),
    ("lost", True, "granted", False),
    ("spam", True, "granted", False),
])
def test_processing_consent_and_closed_leads_fail_closed(lead_status, consent, processing, expected):
    assert operationally_eligible(
        lead_status=lead_status,
        lead_consent=consent,
        processing_consent=processing,
    ) is expected
