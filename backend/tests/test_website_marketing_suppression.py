"""Signed marketing preference links must not authorize sessions or GET mutations."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from northstar_api.lead_crm.website_marketing_suppression import (
    InvalidUnsubscribeToken,
    make_unsubscribe_token,
    verify_unsubscribe_token,
)

SECRET = "testing-only-marketing-unsubscribe-secret-long-enough"


def test_signed_unsubscribe_targets_only_one_lead_and_expires():
    tenant_id, workspace_id, lead_id = uuid4(), uuid4(), uuid4()
    current = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
    token = make_unsubscribe_token(
        tenant_id=tenant_id, workspace_id=workspace_id,
        lead_id=lead_id, secret=SECRET, now=current,
    )
    assert "@" not in token and str(lead_id) not in token
    target = verify_unsubscribe_token(token, secret=SECRET, now=current)
    assert (target.tenant_id, target.workspace_id, target.lead_id) == (
        tenant_id, workspace_id, lead_id,
    )
    assert target.expires_at > current + timedelta(days=29)
    with pytest.raises(InvalidUnsubscribeToken):
        verify_unsubscribe_token(
            token, secret=SECRET,
            now=current + timedelta(days=31),
        )


@pytest.mark.parametrize("change", [
    lambda value: value[:-1] + ("A" if value[-1] != "A" else "B"),
    lambda value: "invalid",
    lambda value: value + ".extra",
    lambda value: value[:50] + "invalid_" + value[50:],
    lambda value: "z" * 800,
])
def test_tampered_or_unsupported_tokens_are_rejected(change):
    current = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
    token = make_unsubscribe_token(
        tenant_id=uuid4(), workspace_id=uuid4(),
        lead_id=uuid4(), secret=SECRET, now=current,
    )
    with pytest.raises(InvalidUnsubscribeToken):
        verify_unsubscribe_token(change(token), secret=SECRET, now=current)


def test_wrong_signing_key_cannot_authenticate_link():
    token = make_unsubscribe_token(
        tenant_id=uuid4(), workspace_id=uuid4(), lead_id=uuid4(),
        secret=SECRET,
    )
    with pytest.raises(InvalidUnsubscribeToken):
        verify_unsubscribe_token(token, secret="an-unrelated-production-secret-key-over-32-characters")


def test_short_secrets_fail_closed():
    with pytest.raises(ValueError):
        make_unsubscribe_token(
            tenant_id=uuid4(), workspace_id=uuid4(),
            lead_id=uuid4(), secret="unsafe",
        )
