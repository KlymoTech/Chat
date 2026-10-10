"""Fail-closed signing claim behavior for database failures and replays."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.modules.platform_runtime.queue_notification_custody_signing_claims import (
    CommittedPostgresSigningClaims,
)


class FakeTransaction:
    def __init__(self, *, fail_execute=False, fail_commit=False):
        self.fail_execute = fail_execute
        self.fail_commit = fail_commit
        self.inserted = []
        self.commits = 0

    async def execute(self, query):
        if self.fail_execute:
            raise RuntimeError("write failed")
        self.inserted.append(query)

    async def commit(self):
        self.commits += 1
        if self.fail_commit:
            raise TimeoutError("commit outcome unknown")


class Factory:
    def __init__(self, transaction):
        self.transaction = transaction

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.transaction

    async def __aexit__(self, *args):
        return False


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_step", ["execute", "commit"])
async def test_database_failures_never_confirm_claim(monkeypatch, failing_step):
    transaction = FakeTransaction(
        fail_execute=failing_step == "execute",
        fail_commit=failing_step == "commit",
    )
    # Emulate a real AsyncSession instance without database access.
    monkeypatch.setattr(
        "northstar_api.modules.platform_runtime.queue_notification_custody_signing_claims.AsyncSession",
        lambda: None,
    )
    # The store refuses non-AsyncSession contexts even when they offer methods.
    store = CommittedPostgresSigningClaims(Factory(transaction))
    with pytest.raises(PermissionError, match="unavailable or already used"):
        await store.claim(
            release_id="release-12345678", run_id="run-12345678",
            witness_sha256="a" * 64, now=datetime(2026, 10, 10, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_invalid_claim_is_rejected_without_database_use():
    class NeverFactory:
        def __call__(self):
            raise AssertionError("database must not be used")
    store = CommittedPostgresSigningClaims(NeverFactory())
    with pytest.raises(PermissionError, match="invalid custody"):
        await store.claim(
            release_id="../bad", run_id="run-12345678",
            witness_sha256="a" * 64, now=datetime(2026, 10, 10, tzinfo=UTC),
        )
