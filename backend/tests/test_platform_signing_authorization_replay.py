"""Offline checks for the independent, one-use authorization ledger."""
from __future__ import annotations

from datetime import UTC, datetime, tzinfo

import pytest

from northstar_api.modules.platform_runtime import (
    queue_notification_signing_authorization_replay as replay,
)


class NoOffsetTZ(tzinfo):
    def utcoffset(self, dt):
        return None


class FakeSession:
    def __init__(self, *, error=None):
        self.error = error
        self.inserts = 0
        self.commits = 0

    async def execute(self, statement):
        self.inserts += 1
        if self.error == "insert":
            raise RuntimeError("insert failed")

    async def commit(self):
        self.commits += 1
        if self.error == "commit":
            raise TimeoutError("commit result unknown")


class Factory:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_):
        return False


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [None, "insert", "commit"])
async def test_consumption_requires_confirmed_commit(monkeypatch, error):
    session = FakeSession(error=error)
    monkeypatch.setattr(replay, "AsyncSession", FakeSession)
    store = replay.CommittedAuthorizationConsumption(Factory(session))
    arguments = {
        "authorization_id": "unique-auth-id-123456",
        "release_id": "release-12345678",
        "run_id": "jenkins-run-123456",
        "now": datetime(2026, 10, 10, tzinfo=UTC),
    }
    if error:
        with pytest.raises(PermissionError, match="already consumed or unavailable"):
            await store.consume(**arguments)
    else:
        await store.consume(**arguments)
    assert session.inserts == 1
    assert session.commits == (0 if error == "insert" else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"authorization_id": "bad"}, {"release_id": "../bad"},
    {"run_id": "x"}, {"now": datetime(2026, 10, 10)},
    {"now": datetime(2026, 10, 10, tzinfo=NoOffsetTZ())},
])
async def test_invalid_parameters_do_not_touch_database(change):
    class Unreachable:
        def __call__(self):
            raise AssertionError("database must not be contacted")

    store = replay.CommittedAuthorizationConsumption(Unreachable())
    arguments = {
        "authorization_id": "unique-auth-id-123456",
        "release_id": "release-12345678",
        "run_id": "jenkins-run-123456",
        "now": datetime(2026, 10, 10, tzinfo=UTC),
    }
    arguments.update(change)
    with pytest.raises(PermissionError, match="invalid signing authorization"):
        await store.consume(**arguments)


@pytest.mark.asyncio
async def test_database_unavailable_fails_closed():
    class Offline:
        def __call__(self):
            raise ConnectionError("database down")

    store = replay.CommittedAuthorizationConsumption(Offline())
    with pytest.raises(PermissionError, match="already consumed or unavailable"):
        await store.consume(
            authorization_id="unique-auth-id-123456",
            release_id="release-12345678",
            run_id="jenkins-run-123456",
            now=datetime(2026, 10, 10, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_non_session_object_cannot_confirm_authorization():
    class WrongSession:
        async def execute(self, statement):
            raise AssertionError("untrusted session must not execute")

    store = replay.CommittedAuthorizationConsumption(Factory(WrongSession()))
    with pytest.raises(PermissionError, match="already consumed or unavailable"):
        await store.consume(
            authorization_id="unique-auth-id-123456",
            release_id="release-12345678",
            run_id="jenkins-run-123456",
            now=datetime(2026, 10, 10, tzinfo=UTC),
        )


def test_invalid_session_factory_rejected_immediately():
    with pytest.raises(TypeError, match="session factory required"):
        replay.CommittedAuthorizationConsumption(None)
