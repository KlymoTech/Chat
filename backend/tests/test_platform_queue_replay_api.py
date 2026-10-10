"""Platform API tenant isolation and audit tests for dead-letter replay."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from northstar_api.modules.super_admin.api import runtime
from northstar_api.modules.super_admin.api.runtime import (
    QueueDeadLetterReplayRequest,
    replay_platform_dead_letter,
)


def make_session(rowcount: int):
    session = MagicMock()
    session.execute = AsyncMock(return_value=SimpleNamespace(rowcount=rowcount))
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_scoped_replay_is_audited(monkeypatch):
    audit = MagicMock()
    monkeypatch.setattr(runtime, "record_audit_event", audit)
    session = make_session(1)
    principal = SimpleNamespace(tenant_id=uuid4(), user_id=uuid4())
    job_id = uuid4()
    result = await replay_platform_dead_letter(
        job_id, QueueDeadLetterReplayRequest(reason="reviewed after incident"),
        principal, session,
    )
    assert result["replayed"] is True
    stmt = session.execute.await_args.args[0]
    params = stmt.compile().params
    assert principal.tenant_id in params.values()
    assert "dead_letter" in params.values()
    assert "queued" in params.values()
    audit.assert_called_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_tenant_scope_fails_closed():
    session = make_session(1)
    principal = SimpleNamespace(tenant_id=None, user_id=uuid4())
    with pytest.raises(HTTPException) as exc:
        await replay_platform_dead_letter(
            uuid4(), QueueDeadLetterReplayRequest(reason="reviewed after incident"),
            principal, session,
        )
    assert exc.value.status_code == 403
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_dead_letter_or_cross_tenant_replay_is_rejected(monkeypatch):
    audit = MagicMock()
    monkeypatch.setattr(runtime, "record_audit_event", audit)
    session = make_session(0)
    principal = SimpleNamespace(tenant_id=uuid4(), user_id=uuid4())
    with pytest.raises(HTTPException) as exc:
        await replay_platform_dead_letter(
            uuid4(), QueueDeadLetterReplayRequest(reason="reviewed after incident"),
            principal, session,
        )
    assert exc.value.status_code == 409
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
    audit.assert_not_called()
