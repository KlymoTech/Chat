"""Explainable, allowlisted website lead scoring. Never sends or qualifies a lead.

This policy operates on already-collected CRM attribution metadata only. It
does not change the customer's qualification decision or trigger messaging.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RuleField = Literal["source_channel", "utm_source", "utm_medium", "utm_campaign"]


class ScoreRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    field: RuleField
    equals: str = Field(min_length=1, max_length=120)
    points: int = Field(ge=-50, le=50)

    @field_validator("equals")
    @classmethod
    def normalize_value(cls, value: str) -> str:
        stripped = value.strip().casefold()
        if not stripped:
            raise ValueError("Rule value cannot be blank")
        return stripped


class ScorePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: int = Field(default=0, ge=0)
    enabled: bool = False
    base_points: int = Field(default=0, ge=0, le=100)
    review_threshold: int = Field(default=60, ge=1, le=100)
    rules: tuple[ScoreRule, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def unique_rules(self) -> "ScorePolicy":
        pairs = [(item.field, item.equals) for item in self.rules]
        if len(pairs) != len(set(pairs)):
            raise ValueError("A field/value rule can be configured only once")
        return self


class ScorePolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    enabled: bool
    base_points: int = Field(ge=0, le=100)
    review_threshold: int = Field(ge=1, le=100)
    rules: tuple[ScoreRule, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def validate_policy(self) -> "ScorePolicyUpdate":
        ScorePolicy(
            enabled=self.enabled, base_points=self.base_points,
            review_threshold=self.review_threshold, rules=self.rules,
        )
        return self


class RuleExplanation(BaseModel):
    field: RuleField
    equals: str
    points: int
    matched: bool


class ScorePreview(BaseModel):
    lead_id: str
    policy_version: int
    eligible: bool
    ineligible_reason: str | None = None
    current_score: int | None = None
    proposed_score: int | None = None
    review_threshold: int
    recommendation: Literal["review", "below_threshold", "blocked", "disabled"]
    qualification_status: str | None = None
    rules: list[RuleExplanation]


def evaluate_score(
    policy: ScorePolicy,
    *,
    lead_id: str,
    values: dict[str, str | None],
    current_score: int | None,
    qualification_status: str | None,
    consent: bool,
    consent_status: str | None,
    lead_status: str,
) -> ScorePreview:
    permitted = consent and (consent_status or "").lower() not in {
        "denied", "withdrawn", "revoked", "opted_out",
    }
    reason = None
    if not policy.enabled:
        reason = "Scoring policy is disabled"
    elif not permitted:
        reason = "Required processing consent is missing or withdrawn"
    elif lead_status.lower() == "archived":
        reason = "Archived leads cannot be scored"
    explanations: list[RuleExplanation] = []
    score = policy.base_points
    for rule in policy.rules:
        observed = (values.get(rule.field) or "").strip().casefold()
        matched = bool(observed) and observed == rule.equals
        if matched:
            score += rule.points
        explanations.append(RuleExplanation(
            field=rule.field, equals=rule.equals, points=rule.points, matched=matched,
        ))
    score = max(0, min(100, score))
    return ScorePreview(
        lead_id=lead_id,
        policy_version=policy.version,
        eligible=reason is None,
        ineligible_reason=reason,
        current_score=current_score,
        proposed_score=score if reason is None else None,
        review_threshold=policy.review_threshold,
        recommendation=(
            "disabled" if not policy.enabled else
            "blocked" if reason else
            "review" if score >= policy.review_threshold else
            "below_threshold"
        ),
        qualification_status=qualification_status,
        rules=explanations,
    )
