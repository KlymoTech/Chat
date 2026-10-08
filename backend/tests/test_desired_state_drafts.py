"""Desired-state draft writes are immutable, audited and never deployed."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from northstar_api.modules.platform_runtime.contracts import PlatformSpec
from northstar_api.modules.super_admin.api.runtime import (
    DesiredStateDraftRequest,
    create_desired_state_draft,
)


@pytest.mark.asyncio
async def test_create_inactive_revision_without_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    from northstar_api.modules.super_admin.api import runtime

    audit = MagicMock()
    dispatch = MagicMock()
    monkeypatch.setattr(runtime, "record_audit_event", audit)
    monkeypatch.setattr(runtime, "enqueue_event", dispatch)
    session = MagicMock()
    session.scalar = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    request = DesiredStateDraftRequest(desired=PlatformSpec(), reason="baseline snapshot")
    principal = SimpleNamespace(user_id=uuid4(), tenant_id=uuid4())

    result = await create_desired_state_draft(request, principal, session)

    assert result["active"] is False
    assert result["revision"] == 1
    created = session.add.call_args.args[0]
    assert created.active is False
    audit.assert_called_once()
    dispatch.assert_not_called()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_revision_reuse_is_rejected() -> None:
    session = MagicMock()
    session.scalar = AsyncMock(return_value=SimpleNamespace(revision=2))
    request = DesiredStateDraftRequest(desired=PlatformSpec(), reason="duplicate revision")
    principal = SimpleNamespace(user_id=uuid4(), tenant_id=uuid4())
    with pytest.raises(HTTPException) as error:
        await create_desired_state_draft(request, principal, session)
    assert error.value.status_code == 409
    session.add.assert_not_called()
