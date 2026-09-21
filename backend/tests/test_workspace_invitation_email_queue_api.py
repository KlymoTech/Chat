"""HTTP -> committed encrypted job -> scoped worker, with no live SMTP/broker."""
from __future__ import annotations

import hashlib
from types import SimpleNamespace
from uuid import UUID, uuid4

from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.modules.workspace.services import invitation_email_delivery as delivery
from northstar_api.modules.workspace.services.invitation_email_config import InvitationEmailConfig
from northstar_api.security import decode_token
from northstar_api.workers import workspace_invitation_email_tasks as worker


def _queue_mode(monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    config = InvitationEmailConfig(workspace_invitation_delivery_key=key)
    monkeypatch.setattr(delivery, "get_invitation_email_config", lambda: config)
    monkeypatch.setattr(worker, "get_invitation_email_config", lambda: config)
    monkeypatch.setattr(delivery, "get_email_settings", lambda: SimpleNamespace(email_delivery_mode="smtp"))
    monkeypatch.setattr(worker, "get_email_settings", lambda: SimpleNamespace(email_delivery_mode="smtp"))
    return Fernet(key.encode("ascii"))


async def _setup(client, auth_headers):
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    workspace_id = workspace.json()["id"]
    tenant_id = UUID(decode_token(auth_headers["Authorization"].removeprefix("Bearer "), "access")["tid"])
    headers = {**auth_headers, "X-Workspace-ID": workspace_id}
    return tenant_id, workspace_id, headers


async def test_http_invite_commits_secret_job_worker_delivers_once(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch,
) -> None:
    from northstar_api.database import SessionFactory
    from northstar_api.modules.workspace.models.invitation_email_job import WorkspaceInvitationEmailJob
    from northstar_api.workspace_invitations import WorkspaceInvitation

    cipher = _queue_mode(monkeypatch)
    delivered: list[dict[str, object]] = []

    async def capture(**kwargs):
        delivered.append(kwargs)

    monkeypatch.setattr(worker, "send_workspace_invitation_email", capture)
    tenant_id, workspace_id, headers = await _setup(client, auth_headers)
    email = f"encrypted-invite-{uuid4().hex}@example.com"
    issued = await client.post("/api/v1/workspace/invitations", headers=headers, json={
        "email": email, "role": "viewer", "allAgentsAccess": True, "agentIds": [],
    })
    assert issued.status_code == 201, issued.text
    invitation_id = UUID(issued.json()["id"])
    assert issued.json()["deliveryState"] == "not-sent"
    assert not delivered
    try:
        async with SessionFactory() as session:
            job = await session.scalar(select(WorkspaceInvitationEmailJob).where(
                WorkspaceInvitationEmailJob.tenant_id == tenant_id,
                WorkspaceInvitationEmailJob.workspace_id == UUID(workspace_id),
                WorkspaceInvitationEmailJob.invitation_id == invitation_id,
            ))
            assert job is not None
            assert job.status == "queued"
            assert job.ciphertext is not None
            raw = cipher.decrypt(job.ciphertext.encode()).decode()
            assert hashlib.sha256(raw.encode()).hexdigest() == job.token_hash
            invitation = await session.get(WorkspaceInvitation, invitation_id)
            assert invitation is not None
            assert invitation.token_hash == job.token_hash
            job_id = job.id
        await worker.deliver_invitation_email_job(tenant_id, job_id)
        await worker.deliver_invitation_email_job(tenant_id, job_id)
        assert len(delivered) == 1
        assert delivered[0]["raw_token"] == raw
        assert delivered[0]["recipient_email"] == email
        async with SessionFactory() as session:
            finished = await session.get(WorkspaceInvitationEmailJob, job_id)
            assert finished is not None
            assert finished.status == "sent" and finished.ciphertext is None
            updated = await session.get(WorkspaceInvitation, invitation_id)
            assert updated is not None and updated.last_sent_at is not None
    finally:
        revoked = await client.delete(f"/api/v1/workspace/invitations/{invitation_id}", headers=headers)
        assert revoked.status_code == 204, revoked.text


async def test_revoked_invitation_cancels_committed_job_without_sending(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch,
) -> None:
    from northstar_api.database import SessionFactory
    from northstar_api.modules.workspace.models.invitation_email_job import WorkspaceInvitationEmailJob

    _queue_mode(monkeypatch)
    delivered: list[object] = []

    async def capture(**kwargs):
        delivered.append(kwargs)

    monkeypatch.setattr(worker, "send_workspace_invitation_email", capture)
    tenant_id, workspace_id, headers = await _setup(client, auth_headers)
    issued = await client.post("/api/v1/workspace/invitations", headers=headers, json={
        "email": f"revoked-encrypted-{uuid4().hex}@example.com",
        "role": "viewer", "allAgentsAccess": True, "agentIds": [],
    })
    assert issued.status_code == 201, issued.text
    invitation_id = UUID(issued.json()["id"])
    async with SessionFactory() as session:
        job = await session.scalar(select(WorkspaceInvitationEmailJob).where(
            WorkspaceInvitationEmailJob.tenant_id == tenant_id,
            WorkspaceInvitationEmailJob.workspace_id == UUID(workspace_id),
            WorkspaceInvitationEmailJob.invitation_id == invitation_id,
        ))
        assert job is not None
        job_id = job.id
    revoked = await client.delete(f"/api/v1/workspace/invitations/{invitation_id}", headers=headers)
    assert revoked.status_code == 204, revoked.text
    await worker.deliver_invitation_email_job(tenant_id, job_id)
    assert not delivered
    async with SessionFactory() as session:
        cancelled = await session.get(WorkspaceInvitationEmailJob, job_id)
        assert cancelled is not None
        assert cancelled.status == "cancelled" and cancelled.ciphertext is None
