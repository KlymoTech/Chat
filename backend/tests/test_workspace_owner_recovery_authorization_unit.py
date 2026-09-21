"""Recovery authentication is checked before any recovery database operation."""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException, Response

from northstar_api.models import Role, WorkspaceRole
from northstar_api.modules.workspace.api.owner_recovery import (
    WorkspaceOwnerRecovery, recover_owner,
)
from northstar_api.security import Principal


@pytest.mark.parametrize('organization_role,token_id,expected_status', [
    (Role.ADMIN, 'interactive-session', 403),
    (Role.MEMBER, 'interactive-session', 403),
    (Role.OWNER, 'api_key:test-key', 403),
])
async def test_recovery_rejects_untrusted_actor_before_using_session(
    organization_role: Role, token_id: str, expected_status: int,
) -> None:
    principal = Principal(
        user_id=uuid4(), tenant_id=uuid4(), role=organization_role,
        token_id=token_id, workspace_id=uuid4(), workspace_role=WorkspaceRole.ADMIN,
        permissions=frozenset({'members.manage'}),
    )
    request = WorkspaceOwnerRecovery(
        target_user_id=uuid4(), reason='recorded_owner_unavailable', confirmation='RECOVER',
    )
    with pytest.raises(HTTPException) as caught:
        await recover_owner(request, principal, object(), Response())  # type: ignore[arg-type]
    assert caught.value.status_code == expected_status
