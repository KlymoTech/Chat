"""Versioned internal-only lead review automations for the existing CRM.

The first supported action queues deduplicated *in-app* administrator reviews.
No customer-facing send, CRM mutation, scheduling or marketing permission is
derived from this model. Reference existing purpose-limited Lead segments.
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class InternalAutomation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID
    name: str = Field(min_length=3, max_length=100)
    segment_id: UUID
    enabled: bool = False
    action: Literal["notify_admins"] = "notify_admins"
    max_per_run: int = Field(default=25, ge=1, le=50)

    @field_validator("name")
    @classmethod
    def name_is_readable(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3 or any(ord(char) < 32 for char in value):
            raise ValueError("Automation name must be readable")
        return value


class InternalAutomationRegister(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: int = Field(default=0, ge=0)
    automations: tuple[InternalAutomation, ...] = Field(default=(), max_length=12)

    @model_validator(mode="after")
    def unique_automations(self) -> "InternalAutomationRegister":
        if len({item.id for item in self.automations}) != len(self.automations):
            raise ValueError("Automation IDs must be unique")
        return self


class InternalAutomationRegisterUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    automations: tuple[InternalAutomation, ...] = Field(max_length=12)


class InternalAutomationExecute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_policy_version: int = Field(ge=1)
    expected_segment_version: int = Field(ge=1)
    expected_eligible_leads: int = Field(ge=0, le=500)


def operationally_eligible(
    *,
    lead_status: str,
    lead_consent: bool,
    processing_consent: str | None,
) -> bool:
    """Never run internal automation on unknown or withdrawn processing consent."""
    return (
        lead_status.strip().lower() not in {"archived", "lost", "spam"}
        and lead_consent
        and (processing_consent or "").strip().casefold()
        in {"granted", "consented", "accepted", "opted_in"}
    )
