"""Qualification governance is independent, fenced, and transactionally audited."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from northstar_api.modules.platform_runtime.queue_notification_qualification_governance import (
    QualificationGovernanceConflict, change_qualification_status,
)


@pytest.mark.asyncio
async def test_independent_approval_advances_revision_and_audits():
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(rowcount=1))
    audit = AsyncMock()
    revision = await change_qualification_status(
        db, qualification_id="cert-12345678", expected_revision=1,
        actor_id="independent-reviewer", authorized=True,
        action="approve", audit=audit,
    )
    assert revision == 2
    query = db.execute.await_args.args[0]
    assert "issued_by" in str(query)
    assert "approved_by" in str(query)
    assert "revision" in str(query)
    audit.assert_awaited_once()
    assert audit.await_args.args[0] is db


@pytest.mark.asyncio
async def test_revocation_is_fenced_and_audited():
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(rowcount=1))
    audit = AsyncMock()
    assert await change_qualification_status(
        db, qualification_id="cert-12345678", expected_revision=2,
        actor_id="incident-operator", authorized=True,
        action="revoke", audit=audit,
    ) == 3
    params = db.execute.await_args.args[0].compile().params
    assert False in params.values()
    assert True in params.values()
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_stale_revision_and_conflict_never_emit_success_audit():
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(rowcount=0))
    audit = AsyncMock()
    with pytest.raises(QualificationGovernanceConflict):
        await change_qualification_status(
            db, qualification_id="cert-12345678", expected_revision=1,
            actor_id="reviewer", authorized=True, action="approve", audit=audit,
        )
    audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_permission_does_not_touch_database():
    db = MagicMock()
    audit = AsyncMock()
    with pytest.raises(PermissionError):
        await change_qualification_status(
            db, qualification_id="cert-12345678", expected_revision=1,
            actor_id="reviewer", authorized=False, action="revoke", audit=audit,
        )
    db.execute.assert_not_called()
    audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_bad_transition_fails_closed():
    db = MagicMock()
    with pytest.raises(ValueError):
        await change_qualification_status(
            db, qualification_id="cert-12345678", expected_revision=1,
            actor_id="reviewer", authorized=True, action="reset", audit=AsyncMock(),
        )
    db.execute.assert_not_called()
