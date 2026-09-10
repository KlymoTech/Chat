from __future__ import annotations

import asyncio
import hashlib
import html
import secrets
import smtplib
import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from urllib.parse import quote

import structlog
from sqlalchemy import DateTime, ForeignKey, Index, String, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.config import get_settings
from northstar_api.database import Base
from northstar_api.email_config import EmailSettings, get_email_settings
from northstar_api.models import WorkspaceRole, enum_column

logger = structlog.get_logger(__name__)


class WorkspaceInvitation(Base):
    __tablename__ = "workspace_invitations"
    __table_args__ = (
        Index("ix_workspace_invitations_workspace_email", "workspace_id", "email"),
        Index("ix_workspace_invitations_tenant_status", "tenant_id", "accepted_at", "revoked_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320), index=True)
    role: Mapped[WorkspaceRole] = mapped_column(enum_column(WorkspaceRole, "workspace_invitation_role"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class WorkspaceInvitationError(RuntimeError):
    pass


def invitation_token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def invitation_url(raw_token: str, settings: EmailSettings | None = None) -> str:
    config = settings or get_email_settings()
    base = config.workspace_invitation_frontend_url.split("#", 1)[0]
    return f"{base}#invite={quote(raw_token, safe='')}"


async def issue_workspace_invitation(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    workspace_id: uuid.UUID,
    email: str,
    role: WorkspaceRole,
    invited_by: uuid.UUID,
    settings: EmailSettings | None = None,
) -> tuple[WorkspaceInvitation, str]:
    config = settings or get_email_settings()
    normalized_email = email.strip().lower()
    now = datetime.now(UTC)
    await session.execute(
        update(WorkspaceInvitation)
        .where(
            WorkspaceInvitation.tenant_id == tenant_id,
            WorkspaceInvitation.workspace_id == workspace_id,
            WorkspaceInvitation.email == normalized_email,
            WorkspaceInvitation.accepted_at.is_(None),
            WorkspaceInvitation.revoked_at.is_(None),
        )
        .values(revoked_at=now, updated_at=now)
    )
    raw_token = secrets.token_urlsafe(48)
    invitation = WorkspaceInvitation(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        email=normalized_email,
        role=role,
        token_hash=invitation_token_hash(raw_token),
        invited_by=invited_by,
        expires_at=now + timedelta(hours=config.workspace_invitation_ttl_hours),
    )
    session.add(invitation)
    await session.flush()
    return invitation, raw_token


async def resolve_workspace_invitation(
    session: AsyncSession,
    raw_token: str,
) -> WorkspaceInvitation:
    invitation = await session.scalar(
        select(WorkspaceInvitation).where(
            WorkspaceInvitation.token_hash == invitation_token_hash(raw_token)
        )
    )
    if invitation is None:
        raise WorkspaceInvitationError("Workspace invitation is invalid or expired")
    now = datetime.now(UTC)
    expires_at = invitation.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if invitation.accepted_at is not None or invitation.revoked_at is not None or expires_at <= now:
        raise WorkspaceInvitationError("Workspace invitation is invalid or expired")
    return invitation


def _smtp_send(message: EmailMessage, settings: EmailSettings) -> None:
    if settings.smtp_ssl:
        client: smtplib.SMTP = smtplib.SMTP_SSL(
            settings.smtp_host,
            settings.smtp_port,
            timeout=settings.smtp_timeout_seconds,
        )
    else:
        client = smtplib.SMTP(
            settings.smtp_host,
            settings.smtp_port,
            timeout=settings.smtp_timeout_seconds,
        )
    try:
        if settings.smtp_starttls:
            client.starttls()
        if settings.smtp_username:
            client.login(
                settings.smtp_username,
                settings.smtp_password.get_secret_value() if settings.smtp_password else "",
            )
        client.send_message(message)
    finally:
        try:
            client.quit()
        except smtplib.SMTPException:
            client.close()


async def send_workspace_invitation_email(
    *,
    email: str,
    workspace_name: str,
    raw_token: str,
    settings: EmailSettings | None = None,
) -> None:
    config = settings or get_email_settings()
    url = invitation_url(raw_token, config)
    if config.email_delivery_mode == "log":
        if get_settings().is_production:
            raise WorkspaceInvitationError("Email delivery is not configured")
        logger.info(
            "workspace_invitation_email_development",
            email=email,
            workspace_name=workspace_name,
            invitation_url=url,
        )
        return

    message = EmailMessage()
    message["Subject"] = f"You have been invited to {workspace_name} on Northstar"
    message["From"] = f"{config.email_from_name} <{config.email_from_address}>"
    message["To"] = email
    message.set_content(
        f"You have been invited to join {workspace_name} on Northstar.\n\n"
        f"Create your account and accept the invitation here:\n{url}\n\n"
        f"This invitation expires in {config.workspace_invitation_ttl_hours} hours."
    )
    safe_workspace = html.escape(workspace_name)
    safe_url = html.escape(url, quote=True)
    message.add_alternative(
        f"<p>You have been invited to join <strong>{safe_workspace}</strong> on Northstar.</p>"
        f'<p><a href="{safe_url}">Join workspace</a></p>'
        f"<p>This invitation expires in {config.workspace_invitation_ttl_hours} hours.</p>",
        subtype="html",
    )
    await asyncio.to_thread(_smtp_send, message, config)
