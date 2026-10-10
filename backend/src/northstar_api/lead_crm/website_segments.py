"""Bounded purpose-aware CRM segments (Blueprint Chapter 46).

Segments refer ONLY to existing Lead/LeadProfile fields and never execute
user-provided SQL, scripts, regex, or behavioral/protected-trait enrichment.
Preview is not authorization to export contacts or dispatch marketing.
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SegmentField = Literal[
    "source_channel", "utm_source", "utm_medium", "utm_campaign",
    "lifecycle_status", "qualification_status",
]
SegmentPurpose = Literal["operations", "marketing"]
SegmentLogic = Literal["all", "any"]


class SegmentCondition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field: SegmentField
    equals: str = Field(min_length=1, max_length=160)

    @field_validator("equals")
    @classmethod
    def normalize(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not normalized or any(ord(char) < 32 for char in normalized):
            raise ValueError("A non-empty readable comparison value is required")
        return normalized


class WebsiteSegment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    name: str = Field(min_length=3, max_length=100)
    purpose: SegmentPurpose = "operations"
    enabled: bool = False
    logic: SegmentLogic = "all"
    include: tuple[SegmentCondition, ...] = Field(min_length=1, max_length=6)
    exclude: tuple[SegmentCondition, ...] = Field(default=(), max_length=6)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        trimmed = value.strip()
        if len(trimmed) < 3:
            raise ValueError("Segment name is too short")
        return trimmed

    @model_validator(mode="after")
    def unique_rules(self) -> "WebsiteSegment":
        for rules in (self.include, self.exclude):
            seen = [(rule.field, rule.equals) for rule in rules]
            if len(set(seen)) != len(seen):
                raise ValueError("Duplicate segment conditions are not allowed")
        return self


class SegmentRegister(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(default=0, ge=0)
    segments: tuple[WebsiteSegment, ...] = Field(default=(), max_length=15)

    @model_validator(mode="after")
    def unique_segments(self) -> "SegmentRegister":
        if len({item.id for item in self.segments}) != len(self.segments):
            raise ValueError("Segment IDs must be unique")
        return self


class SegmentRegisterUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    segments: tuple[WebsiteSegment, ...] = Field(max_length=15)


def matches_segment(
    segment: WebsiteSegment,
    values: dict[str, str | None],
) -> tuple[bool, bool]:
    """Return membership and whether relevant inputs were missing/unknown."""
    def result(rule: SegmentCondition) -> bool | None:
        raw = values.get(rule.field)
        if raw is None or not str(raw).strip():
            return None
        return str(raw).strip().casefold() == rule.equals

    include_results = [result(rule) for rule in segment.include]
    exclude_results = [result(rule) for rule in segment.exclude]
    included = (
        all(value is True for value in include_results) if segment.logic == "all"
        else any(value is True for value in include_results)
    )
    excluded = any(value is True for value in exclude_results)
    missing = any(value is None for value in include_results + exclude_results)
    return included and not excluded, missing
