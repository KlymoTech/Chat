"""Transactional encrypted invitation email outbox and existing-Celery dispatch.

Only a tenant ID and an opaque job ID travel through RabbitMQ. Invitation URLs,
raw tokens, encrypted tokens and email addresses never enter ordinary domain
outbox/audit payloads or the queue message. Broker delivery is at-least-once.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.config import get_settings
from northstar_api.email_config import get_email_settings
from northstar_api.modules.workspace.models.invitation_email_job import WorkspaceInvitationEmailJob
from northstar_api.modules.workspace.services.invitation_email_config import (
    InvitationEmailConfigurationError,
    get_invitation_email_config,
    invitation_cipher,
)
from northstar_api.workspace_invitations import WorkspaceInvitation, WorkspaceInvitationStatus

logger = structlog.get_logger(__name__)
MAX_DISPATCH_ATTEMPTS = 8


class WorkspaceInvitationEmailUnavailable(RuntimeError):
    status_code = 503


def stage_invitation_email(
    session: AsyncSession, *, invitation: WorkspaceInvitation, raw_token: str,
) -> bool:
    """Enqueue encrypted credentials in the invitation transaction, or use dev fallback.

    Production and staging fail closed if the independently managed Fernet key,
    worker dispatcher or SMTP delivery mode is missing. Test/development without
    the feature key retain their existing synchronous sender for compatibility.
    """
    settings = get_settings()
    try:
        cipher = invitation_cipher(get_invitation_email_config())
    except InvitationEmailConfigurationError as exc:
        raise WorkspaceInvitationEmailUnavailable(str(exc)) from None
    if cipher is None:
        if settings.app_env in {"production", "staging"}:
            raise WorkspaceInvitationEmailUnavailable("Workspace invitation email encryption is not configured")
        return False
    if settings.app_env in {"production", "staging"} and not settings.background_dispatch_enabled:
        raise WorkspaceInvitationEmailUnavailable("Workspace invitation job dispatcher is not enabled")
    if get_email_settings().email_delivery_mode != "smtp":
        raise WorkspaceInvitationEmailUnavailable("Workspace invitation SMTP delivery is not configured")
    fingerprint = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    if invitation.status != WorkspaceInvitationStatus.PENDING or invitation.token_hash != fingerprint:
        raise WorkspaceInvitationEmailUnavailable("Workspace invitation changed before mail was queued")
    session.add(WorkspaceInvitationEmailJob(
        tenant_id=invitation.tenant_id,
        workspace_id=invitation.workspace_id,
        invitation_id=invitation.id,
        ciphertext=cipher.encrypt(raw_token.encode("utf-8")).decode("ascii"),
        token_hash=fingerprint,
        status="queued",
    ))
    # A resend rotates the token: the earlier email no longer describes the
    # current invitation, so avoid reporting it as delivery of the new token.
    invitation.last_sent_at = None
    invitation.last_delivery_error = None
    return True


async def dispatch_invitation_email_jobs(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Called inside the existing job-dispatcher DB transaction.

    A committed row survives broker outages; repeated publication is safe
    because the worker locks the row and rejects sent or superseded jobs.
    """
    from northstar_api.workers.workspace_invitation_email_tasks import send_workspace_invitation_email_task

    clock = now or datetime.now(UTC)
    pending = (await session.scalars(
        select(WorkspaceInvitationEmailJob)
        .where(
            WorkspaceInvitationEmailJob.status.in_(("queued", "failed")),
            or_(
                WorkspaceInvitationEmailJob.next_dispatch_at.is_(None),
                WorkspaceInvitationEmailJob.next_dispatch_at <= clock,
            ),
        )
        .order_by(WorkspaceInvitationEmailJob.created_at)
        .with_for_update(skip_locked=True)
        .limit(30)
    )).all()
    dispatched = 0
    for job in pending:
        if job.dispatch_attempts >= MAX_DISPATCH_ATTEMPTS:
            job.status = "dispatch_failed"
            job.ciphertext = None
            job.last_error = "BrokerUnavailable"
            continue
        try:
            await asyncio.to_thread(
                send_workspace_invitation_email_task.apply_async,
                args=[str(job.tenant_id), str(job.id)],
                queue="workspace.email",
                routing_key="workspace.email",
                retry=True,
            )
            job.status = "queued"
            job.dispatch_attempts += 1
            job.dispatched_at = clock
            # Re-offer if RabbitMQ accepted the task but no worker acknowledged.
            job.next_dispatch_at = clock + timedelta(minutes=5)
            dispatched += 1
        except Exception as exc:
            job.dispatch_attempts += 1
            job.last_error = type(exc).__name__[:120]
            if job.dispatch_attempts >= MAX_DISPATCH_ATTEMPTS:
                job.status = "dispatch_failed"
                job.ciphertext = None
            else:
                job.next_dispatch_at = clock + timedelta(seconds=min(300, 2 ** job.dispatch_attempts))
            logger.warning(
                "workspace_invitation_broker_unavailable",
                job_id=str(job.id), error=type(exc).__name__,
            )
    return dispatched
