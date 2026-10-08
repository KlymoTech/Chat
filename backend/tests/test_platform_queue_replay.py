"""Dead-letter replay rejects unauthorized, wrong-tenant and active jobs."""
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from northstar_api.modules.platform_runtime.queue_replay import QueueReplayService, ReplayConflict


def db(*, updated: int = 1):
    session = MagicMock()
    session.execute = AsyncMock()
    session.execute.return_value.rowcount = updated
    session.begin.return_value.__aenter__ = AsyncMock()
    session.begin.return_value.__aexit__ = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock()
    return MagicMock(return_value=session), session


@pytest.mark.asyncio
async def test_authorized_replay_requires_transactional_audit():
    factory, session = db()
    audit = AsyncMock()
    ids = (uuid4(), uuid4(), uuid4())
    result = await QueueReplayService(factory).replay_dead_letter(
        job_id=ids[0], tenant_id=ids[1], operator_id=ids[2],
        authorized=True, reason="reviewed poison message",
        audit_callback=audit,
    )
    assert result.accepted
    audit.assert_awaited_once()
    payload = audit.await_args.args[1]
    assert payload["tenant_id"] == str(ids[1])
    assert payload["operator_id"] == str(ids[2])
    statement = session.execute.await_args.args[0]
    compiled = statement.compile()
    assert "dead_letter" in str(compiled.params.values())
    assert "queued" in str(compiled.params.values())


@pytest.mark.asyncio
async def test_replay_of_non_dead_letter_or_other_tenant_fails_closed():
    factory, session = db(updated=0)
    audit = AsyncMock()
    with pytest.raises(ReplayConflict):
        await QueueReplayService(factory).replay_dead_letter(
            job_id=uuid4(), tenant_id=uuid4(), operator_id=uuid4(),
            authorized=True, reason="reviewed manual retry", audit_callback=audit,
        )
    audit.assert_not_awaited()
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_unauthorized_operation_never_touches_database():
    factory, session = db()
    with pytest.raises(PermissionError):
        await QueueReplayService(factory).replay_dead_letter(
            job_id=uuid4(), tenant_id=uuid4(), operator_id=uuid4(),
            authorized=False, reason="manual replay requested",
            audit_callback=AsyncMock(),
        )
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_audit_hook_or_reason_is_rejected():
    factory, session = db()
    service = QueueReplayService(factory)
    with pytest.raises(ValueError):
        await service.replay_dead_letter(
            job_id=uuid4(), tenant_id=uuid4(), operator_id=uuid4(),
            authorized=True, reason="short", audit_callback=AsyncMock(),
        )
    with pytest.raises(ValueError):
        await service.replay_dead_letter(
            job_id=uuid4(), tenant_id=uuid4(), operator_id=uuid4(),
            authorized=True, reason="reviewed request from SRE", audit_callback=None,
        )
    session.execute.assert_not_awaited()
