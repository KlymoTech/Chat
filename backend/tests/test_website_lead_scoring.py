"""Rule-based CRM scoring is explainable, bounded and purpose-gated."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from northstar_api.lead_crm.website_lead_scoring import (
    ScorePolicy, ScorePolicyUpdate, evaluate_score,
)


def policy(**overrides) -> ScorePolicy:
    return ScorePolicy.model_validate({
        "version": 2, "enabled": True, "base_points": 10,
        "review_threshold": 45,
        "rules": [
            {"field": "source_channel", "equals": "Widget", "points": 25},
            {"field": "utm_source", "equals": "google", "points": 20},
        ],
        **overrides,
    })


def score(config: ScorePolicy, *, consent: bool = True,
          consent_status: str = "granted", lead_status: str = "new"):
    return evaluate_score(
        config, lead_id="lead-123",
        values={"source_channel": "WIDGET", "utm_source": "Google",
                "utm_medium": "organic", "utm_campaign": None},
        current_score=5, qualification_status="pending", consent=consent,
        consent_status=consent_status, lead_status=lead_status,
    )


def test_matching_is_casefolded_explainable_and_requires_human_review():
    preview = score(policy())
    assert preview.eligible
    assert preview.proposed_score == 55
    assert preview.recommendation == "review"
    assert preview.review_threshold == 45
    assert preview.qualification_status == "pending"
    assert [rule.matched for rule in preview.rules] == [True, True]
    assert [rule.points for rule in preview.rules] == [25, 20]


def test_disabled_policy_and_withdrawal_never_score():
    assert score(policy(enabled=False)).recommendation == "disabled"
    assert score(policy(), consent=False).proposed_score is None
    assert score(policy(), consent_status="withdrawn").recommendation == "blocked"
    assert score(policy(), lead_status="archived").eligible is False


def test_points_clamp_and_nonmatching_rules_do_not_add_score():
    config = policy(base_points=97, rules=[
        {"field": "utm_campaign", "equals": "absent-campaign", "points": 50},
    ])
    preview = score(config)
    assert preview.proposed_score == 97
    assert preview.rules[0].matched is False
    config = policy(base_points=0, rules=[
        {"field": "source_channel", "equals": "widget", "points": -50},
    ])
    assert score(config).proposed_score == 0


@pytest.mark.parametrize("rule", [
    {"field": "email", "equals": "person@example.com", "points": 10},
    {"field": "source_channel", "equals": "", "points": 10},
    {"field": "utm_source", "equals": "google", "points": 100},
])
def test_sensitive_or_invalid_rule_definitions_are_refused(rule):
    with pytest.raises(ValidationError):
        policy(rules=[rule])


def test_duplicate_conditions_and_massive_rule_lists_are_refused():
    with pytest.raises(ValidationError):
        policy(rules=[
            {"field": "utm_source", "equals": "google", "points": 10},
            {"field": "utm_source", "equals": "GOOGLE", "points": 20},
        ])
    with pytest.raises(ValidationError):
        ScorePolicyUpdate.model_validate({
            "expected_version": 0, "enabled": True, "base_points": 0,
            "review_threshold": 50,
            "rules": [{"field": "utm_source", "equals": str(i), "points": 2}
                      for i in range(21)],
        })
