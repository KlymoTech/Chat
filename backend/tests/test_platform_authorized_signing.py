"""Fail-closed ordering for protected signing orchestration."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from northstar_api.modules.platform_runtime import queue_notification_authorized_signing as subject


class SigningClaims:
    async def claim(self, **kwargs):
        return None


class Consumption:
    def __init__(self, events, fail=False):
        self.events = events
        self.fail = fail

    async def consume(self, **kwargs):
        self.events.append("consume")
        if self.fail:
            raise PermissionError("duplicate grant")


def arguments(consumption):
    return dict(
        authorization_token="token",
        authorization_public_key_pem=b"key",
        authorization_issuer="issuer",
        authorization_audience="audience",
        authorization_consumption=consumption,
        index_reconciler=object(),
        report_reconciler=object(),
        signing_identity=object(),
        signing_claims=SigningClaims(),
        release_id="release-12345678",
        run_id="run-12345678",
        branch="feature/test",
        environment="staging",
        source_commit="a" * 40,
        source_digest="b" * 64,
        target_digest="c" * 64,
        witness_public_key_pem=b"witness",
        test_signer_public_key_pem=b"signer",
        witness_issuer="issuer",
        controller_id="controller",
        job_full_name="job",
        now=datetime(2026, 10, 10, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_grant_is_consumed_before_custody(monkeypatch):
    events = []

    def verify(*args, **kwargs):
        events.append("verify")
        return "authorization-12345678"

    async def sign(*args, **kwargs):
        events.append("custody")
        assert kwargs["run_id"] == "run-12345678"
        return "signed"

    monkeypatch.setattr(subject, "verify_protected_signing_authorization", verify)
    monkeypatch.setattr(subject, "sign_custodied_jenkins_test_result", sign)
    result = await subject.sign_with_protected_authorization(
        None, **arguments(Consumption(events))
    )
    assert result == "signed"
    assert events == ["verify", "consume", "custody"]


@pytest.mark.asyncio
async def test_rejected_or_duplicate_grant_never_reaches_custody(monkeypatch):
    events = []
    sign = AsyncMock()
    monkeypatch.setattr(subject, "sign_custodied_jenkins_test_result", sign)
    monkeypatch.setattr(
        subject, "verify_protected_signing_authorization",
        lambda *args, **kwargs: "authorization-12345678",
    )
    with pytest.raises(PermissionError, match="duplicate"):
        await subject.sign_with_protected_authorization(
            None, **arguments(Consumption(events, fail=True))
        )
    assert events == ["consume"]
    sign.assert_not_awaited()

    def reject(*args, **kwargs):
        raise PermissionError("invalid signature")

    monkeypatch.setattr(subject, "verify_protected_signing_authorization", reject)
    events.clear()
    with pytest.raises(PermissionError, match="invalid signature"):
        await subject.sign_with_protected_authorization(
            None, **arguments(Consumption(events))
        )
    assert events == []
    sign.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_replay_ledger_rejects_request(monkeypatch):
    sign = AsyncMock()
    monkeypatch.setattr(subject, "sign_custodied_jenkins_test_result", sign)
    with pytest.raises(PermissionError, match="replay guards"):
        await subject.sign_with_protected_authorization(
            None, **arguments(None)
        )
    sign.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["signing_claims", "authorization_consumption"])
async def test_both_guards_required_before_any_grant_is_consumed(monkeypatch, missing):
    verify = AsyncMock()
    sign = AsyncMock()
    monkeypatch.setattr(subject, "verify_protected_signing_authorization", verify)
    monkeypatch.setattr(subject, "sign_custodied_jenkins_test_result", sign)
    parameters = arguments(Consumption([]))
    parameters[missing] = None
    with pytest.raises(PermissionError, match="replay guards"):
        await subject.sign_with_protected_authorization(None, **parameters)
    verify.assert_not_awaited()
    sign.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_method", ["consume", "claim"])
async def test_nonfunctional_guard_is_rejected_before_authorization(monkeypatch, missing_method):
    verify = AsyncMock()
    monkeypatch.setattr(subject, "verify_protected_signing_authorization", verify)
    parameters = arguments(Consumption([]))
    if missing_method == "consume":
        parameters["authorization_consumption"] = object()
    else:
        parameters["signing_claims"] = object()
    with pytest.raises(PermissionError, match="service unavailable"):
        await subject.sign_with_protected_authorization(None, **parameters)
    verify.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("clock", [0, False, "", [], {}, datetime(2026, 10, 10)])
async def test_invalid_clock_never_consumes_authorization(monkeypatch, clock):
    verify = AsyncMock()
    sign = AsyncMock()
    monkeypatch.setattr(subject, "verify_protected_signing_authorization", verify)
    monkeypatch.setattr(subject, "sign_custodied_jenkins_test_result", sign)
    events = []
    parameters = arguments(Consumption(events))
    parameters["now"] = clock
    with pytest.raises(PermissionError, match="timezone-aware"):
        await subject.sign_with_protected_authorization(None, **parameters)
    assert events == []
    verify.assert_not_awaited()
    sign.assert_not_awaited()
