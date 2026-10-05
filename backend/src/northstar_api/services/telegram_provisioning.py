from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import ipaddress
import re
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlsplit
from uuid import UUID

import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.config import get_settings
from northstar_api.database import set_tenant_context
from northstar_api.dependencies import _agent_scope, _custom_role_context, _merge_agent_scope
from northstar_api.lead_crm.channel_models import ChannelConnection
from northstar_api.lead_crm.channel_scope import AgentChannelBinding, WorkspaceChannelConnection
from northstar_api.lead_crm.credentials import CredentialStoreError, credential_store
from northstar_api.models import (
    Agent,
    AgentStatus,
    TenantMembership,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceStatus,
)
from northstar_api.modules.workspace.member_state import is_member_suspended
from northstar_api.security import TENANT_ROLE_PERMISSIONS, WORKSPACE_ROLE_PERMISSIONS, Principal
from northstar_api.services.entitlements import EntitlementError, require_channel
from northstar_api.services.telegram import TelegramAPIError, telegram_client
from northstar_api.telegram_provisioning import TelegramProvisioning

logger = structlog.get_logger(__name__)
ACTIVE = {"pending", "awaiting_bot_creation", "awaiting_confirmation", "configuring"}


class ManagedBotUnavailable(TelegramAPIError):
    """The manager no longer has access; a new creation flow is appropriate."""


def public_base() -> str:
    value = get_settings().telegram_public_base_url.strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise HTTPException(503, "Configure a valid public Telegram HTTPS origin") from None
    host = parsed.hostname or ""
    try:
        private = not ipaddress.ip_address(host).is_global
    except ValueError:
        private = host.lower() == "localhost" or host.lower().endswith((".localhost", ".local"))
    if (
        parsed.scheme != "https"
        or not host
        or private
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path
        or port not in {None, 443}
    ):
        raise HTTPException(
            503, "Configure a public HTTPS TELEGRAM_PUBLIC_BASE_URL before connecting Telegram"
        )
    return value


def manager_config() -> tuple[str, str, str]:
    settings = get_settings()
    token = (
        settings.telegram_manager_bot_token.get_secret_value() if settings.telegram_manager_bot_token else ""
    )
    secret = (
        settings.telegram_manager_webhook_secret.get_secret_value()
        if settings.telegram_manager_webhook_secret
        else ""
    )
    username = settings.telegram_manager_bot_username.strip()
    if (
        not token
        or not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username)
        or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", secret)
    ):
        raise HTTPException(
            503, "The platform Telegram manager is not configured. Contact the platform owner."
        )
    public_base()
    return token, username, secret


def webhook_url(connection: ChannelConnection) -> str:
    return f"{public_base()}{get_settings().app_api_prefix}/webhooks/channels/{connection.tenant_id}/telegram/{connection.public_id}"


async def refresh_normal_bot_webhook(
    connection: ChannelConnection,
    *,
    credentials: dict[str, object],
) -> str:
    """Move an existing BotFather connection to the active public origin.

    ngrok development origins change between sessions.  Re-registering during
    an explicit staff health check prevents an otherwise valid Telegram bot
    from remaining tied to the old tunnel.
    """
    token = str(credentials.get("bot_token") or "").strip()
    secret = str(credentials.get("webhook_secret") or "").strip()
    if not token or not secret:
        raise TelegramAPIError("Telegram credentials are not available", requires_reconnect=True)
    expected = webhook_url(connection)
    await telegram_client.set_webhook(
        token,
        url=expected,
        secret_token=secret,
        allowed_updates=["message", "edited_message"],
    )
    info = await telegram_client.get_webhook_info(token)
    if str(info.get("url") or "") != expected or info.get("last_error_message"):
        raise TelegramAPIError("Telegram did not verify the refreshed webhook", retryable=True)
    configuration = dict(connection.configuration_json or {})
    telegram = dict(configuration.get("telegram") or {})
    telegram["webhookUrl"] = expected
    configuration["telegram"] = telegram
    connection.configuration_json = configuration
    return expected


def expired(value: TelegramProvisioning) -> bool:
    return value.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC)


async def validate_agent(session: AsyncSession, principal: Principal, agent_id: UUID) -> Agent:
    if not principal.workspace_id or not principal.can("integrations.manage"):
        raise HTTPException(403, "Workspace integration management permission required")
    if principal.agent_ids is not None and agent_id not in principal.agent_ids:
        raise HTTPException(403, "Agent access is unavailable")
    agent = await session.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.tenant_id == principal.tenant_id,
            Agent.workspace_id == principal.workspace_id,
            Agent.deleted_at.is_(None),
        )
    )
    if not agent:
        raise HTTPException(404, "Agent not found in this workspace")
    binding = await session.scalar(
        select(AgentChannelBinding).where(AgentChannelBinding.agent_id == agent_id)
    )
    if not binding or binding.channel_type != "telegram":
        raise HTTPException(409, "Choose an agent assigned to Telegram")
    try:
        await require_channel(session, tenant_id=principal.tenant_id, provider="telegram")
    except EntitlementError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    return agent


async def connect_normal_bot(
    session: AsyncSession,
    principal: Principal,
    *,
    agent_id: UUID,
    name: str,
    bot_token: str,
) -> ChannelConnection:
    """Connect a BotFather token to the existing generic Telegram channel.

    This deliberately does not depend on the manager/provisioning bot. The
    provider token and webhook secret are encrypted before the connection is
    committed, and neither value is returned from this service.
    """
    agent = await validate_agent(session, principal, agent_id)
    token = bot_token.strip()
    if not token:
        raise HTTPException(422, "A BotFather token is required")
    try:
        identity = await telegram_client.get_me(token)
    except TelegramAPIError as exc:
        if exc.status_code in {400, 401, 403, 404}:
            raise HTTPException(422, "Telegram could not validate that bot token") from None
        raise HTTPException(503, "Telegram is temporarily unavailable. Try again shortly.") from None
    bot_id = str(identity.get("id") or "")
    username = str(identity.get("username") or "")
    if not bot_id or not identity.get("is_bot") or not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
        raise HTTPException(422, "Telegram returned an invalid bot identity")

    all_rows = (
        await session.execute(
            select(ChannelConnection, WorkspaceChannelConnection)
            .join(WorkspaceChannelConnection, WorkspaceChannelConnection.connection_id == ChannelConnection.id)
            .where(
                ChannelConnection.tenant_id == principal.tenant_id,
                ChannelConnection.provider == "telegram",
            )
        )
    ).all()
    rows = [(connection, scope) for connection, scope in all_rows if scope.workspace_id == principal.workspace_id]
    same_bot = next(
        (
            (connection, scope)
            for connection, scope in all_rows
            if str((connection.configuration_json or {}).get("telegram", {}).get("botId") or "") == bot_id
        ),
        None,
    )
    if same_bot and (same_bot[1].workspace_id != principal.workspace_id or same_bot[1].agent_id != agent.id):
        raise HTTPException(409, "This Telegram bot is already connected in this tenant")
    if same_bot is None and any(connection.name == name for connection, _ in rows):
        raise HTTPException(409, "A channel connection with that name already exists in this workspace")
    stored_name = name
    if same_bot is None and any(connection.name == name for connection, _ in all_rows):
        stored_name = f"{name} [{str(principal.workspace_id)[:8]}]"

    secret = secrets.token_urlsafe(32)
    try:
        encrypted = credential_store.encrypt({"bot_token": token, "webhook_secret": secret})
    except CredentialStoreError:
        raise HTTPException(503, "Platform credential encryption is not configured") from None
    connection: ChannelConnection
    if same_bot:
        connection, scope = same_bot
        connection.name = stored_name
        scope.agent_id = agent.id
    else:
        connection = ChannelConnection(
            tenant_id=principal.tenant_id,
            provider="telegram",
            name=stored_name,
            status="configuring",
            configuration_json={},
        )
        session.add(connection)
        await session.flush()
        session.add(WorkspaceChannelConnection(
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            agent_id=agent.id,
            connection_id=connection.id,
        ))

    url = webhook_url(connection)
    connection.status = "configuring"
    connection.credentials_encrypted = encrypted
    connection.credentials_ref = None
    connection.configuration_json = {
        "agentId": str(agent.id),
        "telegram": {
            "mode": "bot",
            "managed": False,
            "botId": bot_id,
            "botName": str(identity.get("first_name") or username),
            "botUsername": username,
            "studentUrl": f"https://t.me/{username}",
            "webhookUrl": url,
        },
    }
    connection.last_error = None
    try:
        await telegram_client.set_webhook(token, url=url, secret_token=secret, allowed_updates=["message", "edited_message"])
        info = await telegram_client.get_webhook_info(token)
    except TelegramAPIError as exc:
        connection.status = "unhealthy"
        connection.last_error = "Telegram webhook setup failed"
        raise HTTPException(502, "Telegram could not register the webhook. Check the public HTTPS URL and try again.") from None
    if str(info.get("url") or "") != url or info.get("last_error_message"):
        connection.status = "unhealthy"
        connection.last_error = "Telegram webhook verification failed"
        raise HTTPException(502, "Telegram did not verify the configured webhook")
    connection.status = "healthy"
    connection.last_health_at = datetime.now(UTC)
    # Education agents begin in draft so they cannot answer before their
    # enrollment boundary exists. A fully verified Telegram connection is the
    # deployment step that makes this channel live; without this transition a
    # healthy new bot accepts webhook traffic but the runtime rejects it before
    # it can create a conversation.
    if agent.status is AgentStatus.DRAFT:
        agent.status = AgentStatus.ACTIVE
    await session.flush()
    return connection


async def reauthorize(session: AsyncSession, value: TelegramProvisioning) -> Agent:
    await set_tenant_context(session, value.tenant_id)
    workspace = await session.get(Workspace, value.workspace_id)
    user = await session.get(User, value.user_id)
    member = await session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == value.workspace_id,
            WorkspaceMembership.user_id == value.user_id,
            WorkspaceMembership.tenant_id == value.tenant_id,
        )
    )
    tenant_member = await session.scalar(
        select(TenantMembership).where(
            TenantMembership.tenant_id == value.tenant_id, TenantMembership.user_id == value.user_id
        )
    )
    if (
        not workspace
        or workspace.tenant_id != value.tenant_id
        or workspace.status != WorkspaceStatus.ACTIVE
        or not user
        or not user.is_active
        or not member
        or not tenant_member
        or is_member_suspended(workspace.settings_json, value.user_id)
    ):
        raise HTTPException(403, "Workspace access is no longer available")
    custom, custom_scope, _, _ = _custom_role_context(workspace, value.user_id)
    principal = Principal(
        user_id=value.user_id,
        tenant_id=value.tenant_id,
        role=tenant_member.role,
        token_id=str(value.id),
        workspace_id=value.workspace_id,
        workspace_role=member.role,
        permissions=TENANT_ROLE_PERMISSIONS[tenant_member.role]
        | WORKSPACE_ROLE_PERMISSIONS[member.role]
        | custom,
        agent_ids=_merge_agent_scope(await _agent_scope(session, member, value.user_id), custom_scope),
    )
    return await validate_agent(session, principal, value.agent_id)


def snapshot(value: TelegramProvisioning, connection: ChannelConnection | None = None) -> dict:
    status = "expired" if value.status in ACTIVE and expired(value) else value.status
    return {
        "sessionId": str(value.id),
        "status": status,
        "connectionId": str(value.connection_id) if value.connection_id else None,
        "error": value.error,
        "bot": (connection.configuration_json or {}).get("telegram") if connection else None,
    }


async def configure(session: AsyncSession, value: TelegramProvisioning, bot_id: str) -> ChannelConnection:
    agent = await reauthorize(session, value)
    value.bot_id = bot_id
    await session.flush()
    manager_token, _, _ = manager_config()
    try:
        token = await telegram_client.get_managed_bot_token(manager_token, bot_id)
    except TelegramAPIError as exc:
        if exc.status_code in {400, 403, 404}:
            raise ManagedBotUnavailable("Managed bot is no longer available") from None
        raise
    identity = await telegram_client.get_me(token)
    username = str(identity.get("username") or "")
    if (
        str(identity.get("id")) != bot_id
        or not identity.get("is_bot")
        or not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username)
    ):
        raise TelegramAPIError("Telegram returned an unexpected bot identity")
    logger.info("telegram_bot_identity_verified", provisioning_id=str(value.id))
    # Telegram can restrict a managed bot to its owner. Student authorization
    # belongs to our existing enrollment layer, so permit contact with the bot.
    await telegram_client.allow_managed_bot_students(manager_token, bot_id)
    secret = secrets.token_urlsafe(32)
    encrypted = credential_store.encrypt({"bot_token": token, "webhook_secret": secret})
    connection = (
        await session.get(ChannelConnection, value.connection_id, with_for_update=True)
        if value.connection_id
        else None
    )
    if connection is None:
        connection = ChannelConnection(
            tenant_id=value.tenant_id,
            provider="telegram",
            name=f"Telegram {value.id}",
            status="configuring",
            configuration_json={},
        )
        session.add(connection)
        await session.flush()
        session.add(
            WorkspaceChannelConnection(
                tenant_id=value.tenant_id,
                workspace_id=value.workspace_id,
                agent_id=value.agent_id,
                connection_id=connection.id,
            )
        )
        value.connection_id = connection.id
    value.bot_id = bot_id
    value.status = "configuring"
    connection.credentials_encrypted = encrypted
    connection.configuration_json = {
        "agentId": str(agent.id),
        "telegram": {
            "managed": True,
            "botId": bot_id,
            "botName": str(identity.get("first_name") or username),
            "botUsername": username,
            "studentUrl": f"https://t.me/{username}",
        },
    }
    await session.flush()  # Enforce unique bot claim before external side effects.
    expected = webhook_url(connection)
    await telegram_client.set_webhook(token, url=expected, secret_token=secret)
    info = await telegram_client.get_webhook_info(token)
    if info.get("url") != expected or info.get("last_error_message"):
        raise TelegramAPIError("Telegram webhook verification failed. Connect again to retry.")
    logger.info("telegram_webhook_registered", provisioning_id=str(value.id))
    connection.status = "healthy"
    connection.last_health_at = datetime.now(UTC)
    connection.last_error = None
    if agent.status is AgentStatus.DRAFT:
        agent.status = AgentStatus.ACTIVE
    value.status, value.error = "connected", None
    logger.info(
        "telegram_connection_completed", provisioning_id=str(value.id), connection_id=str(connection.id)
    )
    return connection


def fail(value: TelegramProvisioning, connection: ChannelConnection | None = None) -> None:
    value.status = "failed"
    value.error = (
        "Telegram connection could not be completed. Check platform configuration and Connect again."
    )
    if connection:
        connection.status, connection.last_error = "configuration_error", value.error
    logger.warning("telegram_connection_failed", provisioning_id=str(value.id))


async def start(session: AsyncSession, principal: Principal, agent_id: UUID, *,
                account_id: UUID | None = None, connection_id: UUID | None = None) -> dict:
    await validate_agent(session, principal, agent_id)
    _, username, _ = manager_config()
    credential_store.encrypt({"probe": True})
    query = select(TelegramProvisioning)
    if account_id:
        query = query.where(TelegramProvisioning.id == account_id)
    elif connection_id:
        query = query.where(TelegramProvisioning.connection_id == connection_id)
    else:
        query = query.where(TelegramProvisioning.agent_id == agent_id,
            TelegramProvisioning.tenant_id == principal.tenant_id,
            TelegramProvisioning.workspace_id == principal.workspace_id).order_by(TelegramProvisioning.expires_at.desc())
    value = await session.scalar(query.with_for_update())
    if value and (value.tenant_id != principal.tenant_id or value.workspace_id != principal.workspace_id or value.agent_id != agent_id):
        raise HTTPException(404, "Telegram account not found in this workspace")
    selected_connection_id = value.connection_id if value else connection_id
    connection_query = select(ChannelConnection).join(WorkspaceChannelConnection,
        WorkspaceChannelConnection.connection_id == ChannelConnection.id).where(
        WorkspaceChannelConnection.agent_id == agent_id,
        WorkspaceChannelConnection.workspace_id == principal.workspace_id,
        WorkspaceChannelConnection.tenant_id == principal.tenant_id,
        ChannelConnection.tenant_id == principal.tenant_id,
        ChannelConnection.provider == "telegram")
    connection = None
    if selected_connection_id:
        connection = await session.scalar(connection_query.where(ChannelConnection.id == selected_connection_id))
        if connection is None:
            raise HTTPException(404, "Telegram connection not found in this workspace")
    elif not account_id and not value:
        connection = await session.scalar(connection_query.order_by(ChannelConnection.created_at.desc()))
    if connection_id and not value:
        raise HTTPException(409, "Use Add account to connect a new managed bot")
    if (
        connection
        and connection.status != "disabled"
        and not (connection.configuration_json or {}).get("telegram", {}).get("managed")
    ):
        raise HTTPException(409, "This agent already has a legacy Telegram connection. Disconnect it first.")
    if value and value.status in ACTIVE and not expired(value):
        if value.user_id != principal.user_id:
            raise HTTPException(
                409, "Another administrator is connecting this agent. Try again after that session expires."
            )
        nonce = credential_store.decrypt(value.nonce_encrypted)["nonce"]
        return {**snapshot(value, connection), "telegramUrl": f"https://t.me/{username}?start={nonce}"}
    nonce = secrets.token_urlsafe(32)
    if value is None:
        value = TelegramProvisioning(
            **({"id": account_id} if account_id else {}),
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            agent_id=agent_id,
            user_id=principal.user_id,
        )
        session.add(value)
    value.nonce_hash = hashlib.sha256(nonce.encode()).hexdigest()
    value.nonce_encrypted = credential_store.encrypt({"nonce": nonce})
    value.expires_at = datetime.now(UTC) + timedelta(minutes=10)
    value.request_id = secrets.randbelow(2**31)
    value.user_id = principal.user_id
    value.telegram_user_id = None
    value.status, value.error = "pending", None
    await session.flush()
    if value.bot_id or (
        connection and (connection.configuration_json or {}).get("telegram", {}).get("managed")
    ):
        if connection:
            value.connection_id = connection.id
        retained = value.bot_id or str(connection.configuration_json["telegram"].get("botId") or "")
        try:
            connection = await configure(session, value, retained)
            await session.commit()
            return snapshot(value, connection)
        except ManagedBotUnavailable:
            value.status = "pending"
            value.bot_id = None
            if connection:
                connection.status = "disabled"
                connection.credentials_encrypted = None
                connection.credentials_ref = None
        except TelegramAPIError:
            fail(value, connection)
            await session.commit()
            return snapshot(value, connection)
    logger.info("telegram_provisioning_started", provisioning_id=str(value.id))
    await session.commit()
    return {**snapshot(value), "telegramUrl": f"https://t.me/{username}?start={nonce}"}


def confirmation_data(value: TelegramProvisioning, bot_id: str, secret: str) -> str:
    opaque_id = base64.urlsafe_b64encode(value.id.bytes).decode().rstrip("=")
    data = f"{opaque_id}:{bot_id}"
    signature = hmac.new(secret.encode(), f"{data}:{value.nonce_hash}".encode(), hashlib.sha256).hexdigest()[
        :16
    ]
    return f"{data}:{signature}"


async def manager_event(session: AsyncSession, payload: dict) -> None:
    token, _, secret = manager_config()
    message = payload.get("message") or {}
    text = message.get("text") or ""
    sender = str((message.get("from") or {}).get("id") or "")
    if text.startswith("/start ") and (message.get("chat") or {}).get("type") == "private":
        nonce = text.split(" ", 1)[1].strip()
        value = await session.scalar(
            select(TelegramProvisioning)
            .where(TelegramProvisioning.nonce_hash == hashlib.sha256(nonce.encode()).hexdigest())
            .with_for_update()
        )
        if (
            not value
            or expired(value)
            or value.status not in ACTIVE
            or (value.telegram_user_id and value.telegram_user_id != sender)
        ):
            return
        try:
            agent = await reauthorize(session, value)
        except HTTPException:
            fail(value)
            return
        value.telegram_user_id = sender
        if value.status != "awaiting_confirmation":
            value.status = "awaiting_bot_creation"
        name = agent.name[:64]
        stem = re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_")[:16] or "agent"
        suggested = f"{stem}_{secrets.token_hex(4)}_bot"
        manager_username = get_settings().telegram_manager_bot_username
        create_url = f"https://t.me/newbot/{manager_username}/{suggested}?{urlencode({'name': name})}"
        await telegram_client.send_text(
            token, chat_id=sender,
            text=(f"Set up {name} in two steps:\n"
                  "1. Tap Create bot below and approve the name in Telegram.\n"
                  f"2. Return here and tap Connect to {name}.\n\n"
                  "If Telegram does not open the creation screen, open this chat in the latest Telegram mobile or desktop app.\n\n"
                  f"Creation link: {create_url}"),
            reply_markup={"inline_keyboard": [[{"text": "Create bot", "url": create_url}]]},
        )
        logger.info("telegram_manager_start_received", provisioning_id=str(value.id))
        return
    # Telegram does NOT echo request_id in either creation event. Never assign
    # the latest session. Obtain explicit Telegram confirmation of agent+bot.
    managed = payload.get("managed_bot") or {}
    bot = managed.get("bot") or (message.get("managed_bot_created") or {}).get("bot")
    owner = str((managed.get("user") or {}).get("id") or sender)
    if bot and owner:
        bot_id = str(bot.get("id") or "")
        if not bot_id.isdigit() or await session.scalar(
            select(TelegramProvisioning.id).where(TelegramProvisioning.bot_id == bot_id)
        ):
            return
        values = (
            await session.scalars(
                select(TelegramProvisioning)
                .where(
                    TelegramProvisioning.telegram_user_id == owner,
                    TelegramProvisioning.status.in_(["awaiting_bot_creation", "awaiting_confirmation"]),
                )
                .with_for_update()
            )
        ).all()
        for value in values:
            if expired(value):
                continue
            try:
                agent = await reauthorize(session, value)
            except HTTPException:
                fail(value)
                continue
            value.status = "awaiting_confirmation"
            await telegram_client.send_text(
                token,
                chat_id=owner,
                text=f"Connect @{bot.get('username', '')} to agent {agent.name}? Only confirm the intended agent.",
                reply_markup={
                    "inline_keyboard": [
                        [
                            {
                                "text": f"Connect to {agent.name[:32]}",
                                "callback_data": confirmation_data(value, bot_id, secret),
                            }
                        ]
                    ]
                },
            )
            logger.info("telegram_managed_bot_created", provisioning_id=str(value.id))
        return
    callback = payload.get("callback_query") or {}
    data = str(callback.get("data") or "")
    parts = data.split(":")
    if len(parts) != 3:
        return
    try:
        session_id = UUID(bytes=base64.urlsafe_b64decode(parts[0] + "=="))
    except (ValueError, binascii.Error):
        return
    value = await session.get(TelegramProvisioning, session_id, with_for_update=True)
    if (
        not value
        or expired(value)
        or value.status != "awaiting_confirmation"
        or value.telegram_user_id != str((callback.get("from") or {}).get("id"))
        or not parts[1].isdigit()
        or not hmac.compare_digest(data, confirmation_data(value, parts[1], secret))
    ):
        return
    if await session.scalar(select(TelegramProvisioning.id).where(TelegramProvisioning.bot_id == parts[1])):
        return
    try:
        await configure(session, value, parts[1])
    except (TelegramAPIError, CredentialStoreError, HTTPException):
        connection = (
            await session.get(ChannelConnection, value.connection_id) if value.connection_id else None
        )
        fail(value, connection)
    # Acknowledgement is a convenience; do not roll back a configured connection
    # if Telegram's short callback-answer deadline has passed.
    try:
        await telegram_client.answer_callback(token, str(callback.get("id") or ""))
    except TelegramAPIError:
        pass


async def disconnect(session: AsyncSession, connection: ChannelConnection) -> None:
    value = await session.scalar(
        select(TelegramProvisioning)
        .where(TelegramProvisioning.connection_id == connection.id)
        .with_for_update()
    )
    await session.refresh(connection, with_for_update=True)
    if connection.status == "disabled" and not connection.credentials_encrypted:
        return
    if connection.credentials_encrypted:
        try:
            token = credential_store.decrypt(connection.credentials_encrypted).get("bot_token")
            if token:
                await telegram_client.delete_webhook(token)
        except TelegramAPIError as exc:
            if not exc.requires_reconnect:
                raise HTTPException(
                    503, "Telegram could not remove the webhook. Please retry Disconnect."
                ) from None
        except CredentialStoreError:
            raise HTTPException(
                503, "Restore platform credential encryption before disconnecting Telegram"
            ) from None
    connection.status = "disabled"
    connection.credentials_encrypted = None
    connection.credentials_ref = None
    connection.last_error = None
    if value:
        value.status = "cancelled"
        value.expires_at = datetime.now(UTC)
    logger.info("telegram_disconnected", connection_id=str(connection.id))
