"""Consent policy decisions must always fail closed for non-essential purposes."""
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from northstar_api.services.website_consent_policy import (
    ConsentPreferences, ConsentPurpose, ConsentReceipt, decide_consent,
)

NOW = datetime(2026, 10, 10, tzinfo=UTC)


def receipt(**choices):
    return ConsentReceipt(
        receipt_id="receipt-1", subject_id="anonymous-1", captured_at=NOW,
        source="banner", preferences=ConsentPreferences(policy_version="v1", **choices),
    )


def test_essential_purpose_is_allowed_without_receipt():
    decision = decide_consent(ConsentPurpose.NECESSARY, None, policy_version="v1", at=NOW)
    assert decision.allowed and decision.reason == "essential"


@pytest.mark.parametrize("purpose", [
    ConsentPurpose.ANALYTICS, ConsentPurpose.MARKETING, ConsentPurpose.PERSONALIZATION,
])
def test_nonessential_purposes_require_explicit_consent(purpose):
    assert not decide_consent(purpose, None, policy_version="v1", at=NOW).allowed
    assert not decide_consent(purpose, receipt(), policy_version="v1", at=NOW).allowed


def test_consent_is_granular_and_does_not_cross_purposes():
    current = receipt(analytics=True)
    assert decide_consent(ConsentPurpose.ANALYTICS, current, policy_version="v1", at=NOW).allowed
    assert not decide_consent(ConsentPurpose.MARKETING, current, policy_version="v1", at=NOW).allowed


def test_policy_change_requires_fresh_consent():
    result = decide_consent(ConsentPurpose.ANALYTICS, receipt(analytics=True), policy_version="v2", at=NOW)
    assert result.reason == "policy_changed" and not result.allowed


def test_expired_and_future_receipts_fail_closed():
    enabled = receipt(marketing=True)
    expired = decide_consent(ConsentPurpose.MARKETING, enabled, policy_version="v1", at=NOW + timedelta(days=181))
    future = decide_consent(ConsentPurpose.MARKETING, enabled, policy_version="v1", at=NOW - timedelta(hours=2))
    assert expired.reason == "expired" and not expired.allowed
    assert future.reason == "future_receipt" and not future.allowed


def test_timestamp_must_be_timezone_aware():
    with pytest.raises(ValidationError):
        ConsentReceipt(
            receipt_id="a", subject_id="b", captured_at=datetime(2026, 10, 10),
            source="api", preferences=ConsentPreferences(policy_version="v1"),
        )


def test_unknown_consent_fields_are_rejected():
    with pytest.raises(ValidationError):
        ConsentPreferences(policy_version="v1", advertisements=True)


def test_bad_configuration_is_rejected():
    with pytest.raises(ValueError):
        decide_consent(ConsentPurpose.ANALYTICS, receipt(), policy_version="v1", at=NOW, max_age_days=0)
