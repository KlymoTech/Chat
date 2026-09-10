from __future__ import annotations

import asyncio
import hashlib
import html
import secrets
import smtplib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from urllib.parse import urlencode
from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.email_config import EmailSettings, get_email_settings
from northstar_api.email_verification import EmailVerificationState, EmailVerificationToken
from northstar_api.models import User

logger = structlog.get_logger(__name__)


class EmailVerificationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class IssuedVerification:
    token: str
    expires_at: datetime


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def email_is_verified(session: AsyncSession, user_id: UUID) -> bool:
    state = await session.get(EmailVerificationState, user_id)
    # Legacy users intentionally have no state row and remain verified for compatibility.
    return state is None or state.verified_at is not None


async def ensure_unverified_state(session: AsyncSession, user_id: UUID) -> EmailVerificationState:
    state = await session.get(EmailVerificationState, user_id)
    if state is None:
        state = EmailVerificationState(user_id=user_id, verified_at=None)
        session.add(state)
        await session.flush()
    return state


async def issue_verification_token(
    session: AsyncSession,
    user_id: UUID,
    *,
    settings: EmailSettings | None = None,
) -> IssuedVerification:
    config = settings or get_email_settings()
    now = datetime.now(UTC)
    state = await ensure_unverified_state(session, user_id)
    if state.verified_at is not None:
        raise EmailVerificationError("Email address is already verified")

    await session.execute(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.user_id == user_id,
            EmailVerificationToken.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    raw_token = secrets.token_urlsafe(48)
    expires_at = now + timedelta(hours=config.email_verification_ttl_hours)
    session.add(
        EmailVerificationToken(
            user_id=user_id,
            token_hash=_token_hash(raw_token),
            expires_at=expires_at,
        )
    )
    await session.flush()
    return IssuedVerification(token=raw_token, expires_at=expires_at)


async def verify_email_token(session: AsyncSession, raw_token: str) -> tuple[bool, bool]:
    token = await session.scalar(
        select(EmailVerificationToken).where(EmailVerificationToken.token_hash == _token_hash(raw_token))
    )
    if token is None:
        raise EmailVerificationError("Verification link is invalid or expired")

    state = await session.get(EmailVerificationState, token.user_id)
    if state is None:
        raise EmailVerificationError("Verification link is invalid or expired")
    if state.verified_at is not None:
        return True, True

    now = datetime.now(UTC)
    expires_at = token.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if token.consumed_at is not None or expires_at <= now:
        raise EmailVerificationError("Verification link is invalid or expired")

    state.verified_at = now
    state.updated_at = now
    await session.execute(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.user_id == token.user_id,
            EmailVerificationToken.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    await session.flush()
    return True, False


def verification_url(raw_token: str, settings: EmailSettings | None = None) -> str:
    config = settings or get_email_settings()
    separator = "&" if "?" in config.email_verification_frontend_url else "?"
    return f"{config.email_verification_frontend_url}{separator}{urlencode({'token': raw_token})}"


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


async def send_verification_email(
    user: User,
    raw_token: str,
    *,
    settings: EmailSettings | None = None,
) -> None:
    config = settings or get_email_settings()
    url = verification_url(raw_token, config)
    if config.email_delivery_mode == "log":
        logger.info(
            "verification_email_development",
            user_id=str(user.id),
            email=user.email,
            verification_url=url,
        )
        return

    message = EmailMessage()
    message["Subject"] = "Verify your Northstar email address"
    message["From"] = f"{config.email_from_name} <{config.email_from_address}>"
    message["To"] = user.email
    message.set_content(
        f"Hi {user.name},\n\n"
        "Verify your email address to finish activating your Northstar account.\n\n"
        f"{url}\n\n"
        f"This link expires in {config.email_verification_ttl_hours} hours. "
        "If you did not create this account, you can ignore this email.\n"
    )
    safe_name = html.escape(user.name)
    safe_url = html.escape(url, quote=True)
    message.add_alternative(
        f"<p>Hi {safe_name},</p>"
        "<p>Verify your email address to finish activating your Northstar account.</p>"
        f'<p><a href="{safe_url}">Verify email address</a></p>'
        f"<p>This link expires in {config.email_verification_ttl_hours} hours. "
        "If you did not create this account, you can ignore this email.</p>",
        subtype="html",
    )
    await asyncio.to_thread(_smtp_send, message, config)
