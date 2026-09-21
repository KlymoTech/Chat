"""Existing RabbitMQ/Celery pipeline for Workspace invitation emails.

Tasks carry ONLY tenant/job identifiers. Fetch/decrypt secrets inside the worker,
reject revoked/accepted/expired/superseded invitations, and scrub ciphertext
once it is no longer needed. SMTP is at-least-once, not exactly-once.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from northstar_api.config import get_settings
from northstar_api.database import build_engine, set_tenant_context
from northstar_api.email_config import get_email_settings
from northstar_api.models import Tenant, Workspace, WorkspaceStatus
from northstar_api.modules.workspace.models.invitation_email_job import WorkspaceInvitationEmailJob
from northstar_api.modules.workspace.services.invitation_email_config import (
    InvitationEmailConfigurationError,
    get_invitation_email_config,
    invitation_cipher,
)
from northstar_api.services.workspace_invitations import (
    mark_workspace_invitation_delivery,
    send_workspace_invitation_email,
)
from northstar_api.workspace_invitations import WorkspaceInvitation, WorkspaceInvitationStatus
from northstar_api.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)
MAX_DELIVERY_ATTEMPTS = 8


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def deliver_invitation_email_job(tenant_id: UUID, job_id: UUID) -> None:
    engine = build_engine(get_settings())
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with factory() as session:
            # Apply the same tenant context used by public invitation acceptance.
            await set_tenant_context(session, tenant_id)
            job = await session.scalar(select(WorkspaceInvitationEmailJob).where(
                WorkspaceInvitationEmailJob.id == job_id,
                WorkspaceInvitationEmailJob.tenant_id == tenant_id,
            ).with_for_update())
            if job is None or job.status not in {"queued", "failed"}:
                return
            now = datetime.now(UTC)
            if job.status == "failed" and job.next_dispatch_at is not None and _aware(job.next_dispatch_at) > now:
                return
            invitation = await session.scalar(select(WorkspaceInvitation).where(
                WorkspaceInvitation.id == job.invitation_id,
                WorkspaceInvitation.tenant_id == tenant_id,
                WorkspaceInvitation.workspace_id == job.workspace_id,
            ).with_for_update())
            names = (await session.execute(
                select(Tenant.name, Workspace.name)
                .join(Workspace, Workspace.tenant_id == Tenant.id)
                .where(Tenant.id == tenant_id, Workspace.id == job.workspace_id,
                       Workspace.status == WorkspaceStatus.ACTIVE)
            )).first()
            if (
                invitation is None or names is None
                or invitation.status != WorkspaceInvitationStatus.PENDING
                or _aware(invitation.expires_at) <= now
                or invitation.token_hash != job.token_hash
                or job.ciphertext is None
            ):
                job.status = "cancelled"
                job.ciphertext = None
                job.next_dispatch_at = None
                await session.commit()
                return
            try:
                cipher = invitation_cipher(get_invitation_email_config())
                if cipher is None:
                    raise InvitationEmailConfigurationError("Invitation delivery encryption key unavailable")
                raw_token = cipher.decrypt(job.ciphertext.encode("ascii")).decode("utf-8")
                if hashlib.sha256(raw_token.encode("utf-8")).hexdigest() != job.token_hash:
                    # Corrupt command must never send credentials or leak data.
                    job.status = "cancelled"
                    job.ciphertext = None
                    job.next_dispatch_at = None
                    await session.commit()
                    return
                if get_email_settings().email_delivery_mode != "smtp":
                    raise InvitationEmailConfigurationError("Invitation SMTP delivery unavailable")
                await send_workspace_invitation_email(
                    recipient_email=invitation.email,
                    workspace_name=names[1],
                    tenant_name=names[0],
                    role=invitation.role,
                    raw_token=raw_token,
                )
            except Exception as exc:
                job.delivery_attempts += 1
                job.last_error = type(exc).__name__[:120]
                job.status = "failed" if job.delivery_attempts < MAX_DELIVERY_ATTEMPTS else "delivery_failed"
                job.next_dispatch_at = (
                    now + timedelta(seconds=min(300, 2 ** job.delivery_attempts))
                    if job.status == "failed" else None
                )
                if job.status == "delivery_failed":
                    job.ciphertext = None
                await mark_workspace_invitation_delivery(session, invitation, delivered=False, error=exc)
                await session.commit()
                logger.warning(
                    "workspace_invitation_email_failed", job_id=str(job_id), error=type(exc).__name__,
                )
                return
            job.delivery_attempts += 1
            job.status = "sent"
            job.ciphertext = None
            job.sent_at = datetime.now(UTC)
            job.next_dispatch_at = None
            job.last_error = None
            await mark_workspace_invitation_delivery(session, invitation, delivered=True)
            await session.commit()
    finally:
        await engine.dispose()


@celery_app.task(name="northstar.send_workspace_invitation_email")  # type: ignore[untyped-decorator]
def send_workspace_invitation_email_task(tenant_id: str, job_id: str) -> None:
    asyncio.run(deliver_invitation_email_job(UUID(tenant_id), UUID(job_id)))
