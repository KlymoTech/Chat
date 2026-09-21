"""Invitation SMTP preflight must run only where token rotation needs email config."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException, Request

from northstar_api.modules.workspace.services import invitation_delivery_preflight as preflight


def _request(method: str, route_path: str) -> Request:
    return Request({
        "type": "http", "method": method, "path": route_path,
        "headers": [], "query_string": b"",
        "route": SimpleNamespace(path=route_path),
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("route_path", [
    "/api/v1/workspace/invitations",
    "/api/v1/workspace/invitations/{invitation_id}/resend",
])
async def test_invalid_email_configuration_is_safe_503_before_issue_or_resend(
    monkeypatch: pytest.MonkeyPatch, route_path: str,
) -> None:
    secret = "smtp-password-must-never-leak"
    read_settings = Mock(side_effect=ValueError(secret))
    monkeypatch.setattr(preflight, "get_email_settings", read_settings)
    principal = SimpleNamespace(permissions=frozenset({"members.manage"}))
    with pytest.raises(HTTPException) as raised:
        await preflight.preflight_workspace_invitation_email(
            _request("POST", route_path), principal,
        )
    assert raised.value.status_code == 503
    assert raised.value.detail == "Workspace invitation SMTP delivery is not configured"
    assert secret not in str(raised.value)
    read_settings.assert_called_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize("method,route_path,permissions", [
    ("GET", "/api/v1/workspace/invitations", frozenset({"members.manage"})),
    ("POST", "/api/v1/workspace/members/member-id/suspend", frozenset({"members.manage"})),
    ("POST", "/api/v1/workspace-invitations/signup", frozenset({"members.manage"})),
    ("POST", "/api/v1/workspace/invitations", frozenset({"members.view"})),
])
async def test_preflight_never_changes_unrelated_routes_or_exposes_configuration(
    monkeypatch: pytest.MonkeyPatch,
    method: str, route_path: str, permissions: frozenset[str],
) -> None:
    read_settings = Mock(side_effect=AssertionError("unrelated route read SMTP configuration"))
    monkeypatch.setattr(preflight, "get_email_settings", read_settings)
    await preflight.preflight_workspace_invitation_email(
        _request(method, route_path), SimpleNamespace(permissions=permissions),
    )
    read_settings.assert_not_called()


@pytest.mark.asyncio
async def test_valid_settings_pass_through_without_email_or_database_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_settings = Mock(return_value=SimpleNamespace(email_delivery_mode="smtp"))
    monkeypatch.setattr(preflight, "get_email_settings", read_settings)
    await preflight.preflight_workspace_invitation_email(
        _request("POST", "/api/v1/workspace/invitations"),
        SimpleNamespace(permissions=frozenset({"members.manage"})),
    )
    read_settings.assert_called_once_with()
