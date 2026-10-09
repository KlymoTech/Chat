"""Fenced deployment claims: SQL performs atomic compare-and-swap.

These tests exercise the pure database boundary with deterministic sessions.
Production concurrency and migration still require separate PostgreSQL CI.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from northstar_api.modules.platform_runtime.deployment_leases import (
    DeploymentLeaseService,
)


class FakeSession:
    def __init__(self, rows: int):
        self.execute = AsyncMock(return_value=SimpleNamespace(rowcount=rows))

    def begin(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


def service(rows=1):
    session = FakeSession(rows)
    return DeploymentLeaseService(lambda: session), session


@pytest.mark.asyncio
async def test_newly_approved_claim_receives_unique_fencing_token():
    svc, session = service()
    change_id = uuid4()
    claim = await svc.claim(change_id, owner="jenkins-qualification-42")
    assert claim is not None
    assert claim.change_id == change_id
    assert claim.owner == "jenkins-qualification-42"
    assert claim.lease_token is not None
    statement = session.execute.await_args.args[0]
    sql = str(statement)
    assert "platform_deployment_leases" in sql
    assert "platform_changes" in sql
    assert "platform_config_versions" in sql
    assert "lease_token IS NULL" in sql
    assert "lease_expires_at IS NULL" in sql
    assert "approved" in str(statement.compile().params.values())


@pytest.mark.asyncio
async def test_conflicting_claim_is_fail_closed():
    svc, session = service(rows=0)
    assert await svc.claim(uuid4(), owner="worker-one") is None
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_invalid_worker_identity_never_queries_database():
    svc, session = service()
    with pytest.raises(ValueError, match="worker identity"):
        await svc.claim(uuid4(), owner="")
    with pytest.raises(ValueError, match="worker identity"):
        await svc.claim(uuid4(), owner="x" * 161)
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_expired_or_superseded_renewal_is_rejected():
    svc, _ = service()
    claim = await svc.claim(uuid4(), owner="worker")
    assert claim is not None
    denied, session = service(rows=0)
    assert not await denied.renew(claim)
    statement = session.execute.await_args.args[0]
    sql = str(statement)
    assert "lease_token" in sql
    assert "lease_expires_at >" in sql


@pytest.mark.asyncio
async def test_close_requires_terminal_change_and_matching_token():
    svc, _ = service()
    claim = await svc.claim(uuid4(), owner="worker")
    assert claim is not None
    assert await svc.close(claim)
    # The WHERE clause requires a completed or rolled-back control-plane state.
    checked, session = service(rows=0)
    assert not await checked.close(claim)
    statement = session.execute.await_args.args[0]
    sql = str(statement)
    assert "platform_changes" in sql
    assert "lease_token" in sql
    assert "lease_expires_at >" in sql


def test_invalid_lease_timeout_rejected():
    with pytest.raises(ValueError, match="deployment lease"):
        DeploymentLeaseService(lambda: FakeSession(1), lease_seconds=9)


@pytest.mark.asyncio
async def test_worker_environment_is_bound_to_all_lease_database_operations():
    svc, session = service()
    change_id = uuid4()
    claim = await svc.claim(
        change_id, owner="role/qualified-worker", expected_environment="qualification"
    )
    assert claim is not None
    assert claim.environment == "qualification"
    statement = session.execute.await_args.args[0]
    assert "qualification" in statement.compile().params.values()
    assert await svc.renew(claim, expected_environment="qualification")
    statement = session.execute.await_args.args[0]
    assert "qualification" in statement.compile().params.values()
    assert await svc.close(claim, expected_environment="qualification")
    statement = session.execute.await_args.args[0]
    assert "qualification" in statement.compile().params.values()
