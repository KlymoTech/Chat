from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from northstar_api.routers import workspace as workspace_router_module


async def test_new_user_invitation_is_persisted_and_consumed_during_signup(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: Any,
) -> None:
    captured: dict[str, str] = {}

    async def capture_invitation_email(*, email: str, workspace_name: str, raw_token: str) -> None:
        captured.update(email=email, workspace_name=workspace_name, raw_token=raw_token)

    monkeypatch.setattr(
        workspace_router_module,
        "send_workspace_invitation_email",
        capture_invitation_email,
    )

    before = await client.get("/api/v1/workspace/team", headers=auth_headers)
    assert before.status_code == 200, before.text
    assert before.json()["members"]

    invited = await client.post(
        "/api/v1/workspace/invitations",
        headers=auth_headers,
        json={"email": "invited.member@example.com", "role": "analyst"},
    )
    assert invited.status_code == 201, invited.text
    body = invited.json()
    assert any(item["email"] == "invited.member@example.com" for item in body["invitations"])
    assert captured["email"] == "invited.member@example.com"
    assert len(captured["raw_token"]) >= 32

    persisted = await client.get("/api/v1/workspace/team", headers=auth_headers)
    assert persisted.status_code == 200, persisted.text
    assert any(item["email"] == "invited.member@example.com" for item in persisted.json()["invitations"])

    accepted = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Invited Member",
            "email": "invited.member@example.com",
            "password": "Invited-Password-2026!",
            "workspaceInvitationToken": captured["raw_token"],
            "termsAccepted": True,
            "privacyAccepted": True,
        },
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["user"]["role"] == "member"

    after = await client.get("/api/v1/workspace/team", headers=auth_headers)
    assert after.status_code == 200, after.text
    after_body = after.json()
    invited_member = next(
        item for item in after_body["members"] if item["email"] == "invited.member@example.com"
    )
    assert invited_member["role"] == "analyst"
    assert all(item["email"] != "invited.member@example.com" for item in after_body["invitations"])

    reused = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Invited Member Again",
            "email": "invited.member@example.com",
            "password": "Invited-Password-2026!",
            "workspaceInvitationToken": captured["raw_token"],
            "termsAccepted": True,
            "privacyAccepted": True,
        },
    )
    assert reused.status_code == 409


async def test_existing_account_is_added_without_creating_a_pending_invitation(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: Any,
) -> None:
    existing_email = "existing.member@example.com"
    created = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Existing Member",
            "email": existing_email,
            "password": "Existing-Password-2026!",
            "organizationName": "Existing Member Organization",
            "termsAccepted": True,
            "privacyAccepted": True,
        },
    )
    assert created.status_code == 201, created.text

    async def email_must_not_be_sent(**_: str) -> None:
        raise AssertionError("existing users should be added directly without a pending invitation email")

    monkeypatch.setattr(
        workspace_router_module,
        "send_workspace_invitation_email",
        email_must_not_be_sent,
    )
    added = await client.post(
        "/api/v1/workspace/invitations",
        headers=auth_headers,
        json={"email": existing_email, "role": "operator"},
    )
    assert added.status_code == 201, added.text
    body = added.json()
    member = next(item for item in body["members"] if item["email"] == existing_email)
    assert member["role"] == "operator"
    assert all(item["email"] != existing_email for item in body["invitations"])

    duplicate = await client.post(
        "/api/v1/workspace/invitations",
        headers=auth_headers,
        json={"email": existing_email, "role": "operator"},
    )
    assert duplicate.status_code == 409
