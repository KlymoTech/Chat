"""HTTP regression: invalid mail configuration must fail before invitation mutation."""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import AsyncClient

from northstar_api.modules.workspace.services import invitation_delivery_preflight as preflight
from northstar_api.routers import workspace_invitations as invitation_routes


@pytest.mark.parametrize("action", ["create", "resend"])
async def test_invalid_smtp_fails_before_invitation_service_or_token_rotation(
    client: AsyncClient, auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch, action: str,
) -> None:
    selected = await client.get("/api/v1/workspace", headers=auth_headers)
    assert selected.status_code == 200, selected.text
    headers = {**auth_headers, "X-Workspace-ID": selected.json()["id"]}
    issue = AsyncMock(side_effect=AssertionError("issue service must not be reached"))
    resend = AsyncMock(side_effect=AssertionError("resend service must not be reached"))
    monkeypatch.setattr(invitation_routes, "issue_workspace_invitation", issue)
    monkeypatch.setattr(invitation_routes, "resend_workspace_invitation", resend)
    secret = "smtp-password-must-not-reach-client"

    def invalid_settings():
        raise ValueError(secret)

    monkeypatch.setattr(preflight, "get_email_settings", invalid_settings)
    path = "/api/v1/workspace/invitations"
    if action == "create":
        response = await client.post(path, headers=headers, json={
            "email": f"preflight-{uuid4().hex}@example.test",
            "role": "viewer", "allAgentsAccess": True, "agentIds": [],
        })
    else:
        response = await client.post(f"{path}/{uuid4()}/resend", headers=headers)
    assert response.status_code == 503, response.text
    assert response.json()["detail"] == "Workspace invitation SMTP delivery is not configured"
    assert secret not in response.text
    issue.assert_not_awaited()
    resend.assert_not_awaited()
