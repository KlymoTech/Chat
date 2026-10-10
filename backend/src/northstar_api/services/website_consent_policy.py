"""Purpose-scoped, fail-closed consent decisions for public website telemetry.

This is a pure policy module. The HTTP integration must authenticate updates,
persist receipts, and enforce the result before loading non-essential trackers.
"""
from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConsentPurpose(StrEnum):
    NECESSARY = "necessary"
    ANALYTICS = "analytics"
    MARKETING = "marketing"
    PERSONALIZATION = "personalization"


class ConsentPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: str = Field(min_length=1, max_length=64)
    analytics: bool = False
    marketing: bool = False
    personalization: bool = False

    def permits(self, purpose: ConsentPurpose) -> bool:
        if purpose == ConsentPurpose.NECESSARY:
            return True
        return bool(getattr(self, purpose.value, False))


class ConsentReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt_id: str = Field(min_length=1, max_length=128)
    subject_id: str = Field(min_length=1, max_length=128)
    captured_at: datetime
    source: Literal["banner", "preferences", "api"]
    preferences: ConsentPreferences

    @field_validator("captured_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Consent timestamps must have a timezone")
        return value.astimezone(UTC)


class ConsentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    reason: Literal[
        "essential", "granted", "not_granted", "missing_receipt",
        "policy_changed", "expired", "future_receipt",
    ]


def decide_consent(
    purpose: ConsentPurpose,
    receipt: ConsentReceipt | None,
    *,
    policy_version: str,
    at: datetime,
    max_age_days: int = 180,
) -> ConsentDecision:
    """Return a purpose-specific decision without implicit opt-in or side effects."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("Decision timestamp must have a timezone")
    if not policy_version or max_age_days <= 0:
        raise ValueError("Invalid consent policy configuration")
    if purpose == ConsentPurpose.NECESSARY:
        return ConsentDecision(allowed=True, reason="essential")
    if receipt is None:
        return ConsentDecision(allowed=False, reason="missing_receipt")
    if receipt.preferences.policy_version != policy_version:
        return ConsentDecision(allowed=False, reason="policy_changed")
    seconds = (at.astimezone(UTC) - receipt.captured_at).total_seconds()
    if seconds < -60:
        return ConsentDecision(allowed=False, reason="future_receipt")
    if seconds > max_age_days * 86400:
        return ConsentDecision(allowed=False, reason="expired")
    if not receipt.preferences.permits(purpose):
        return ConsentDecision(allowed=False, reason="not_granted")
    return ConsentDecision(allowed=True, reason="granted")
