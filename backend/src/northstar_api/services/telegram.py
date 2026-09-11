from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

TELEGRAM_API_BASE = "https://api.telegram.org"
TELEGRAM_TEXT_LIMIT = 4096


@dataclass(slots=True)
class TelegramAPIError(RuntimeError):
    message: str
    status_code: int | None = None
    retryable: bool = False
    requires_reconnect: bool = False
    retry_after_seconds: int | None = None

    def __str__(self) -> str:
        return self.message


def split_telegram_text(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    value = text.strip()
    if not value:
        return []
    if limit < 1:
        raise ValueError("Telegram text chunk limit must be positive")
    chunks: list[str] = []
    remaining = value
    while len(remaining) > limit:
        window = remaining[:limit]
        split_at = max(window.rfind("\n"), window.rfind(" "))
        if split_at < max(1, limit // 2):
            split_at = limit
        chunk = remaining[:split_at].rstrip()
        if not chunk:
            chunk = remaining[:limit]
            split_at = len(chunk)
        chunks.append(chunk)
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


class TelegramBotClient:
    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _method_url(bot_token: str, method: str) -> str:
        token = bot_token.strip()
        if not token:
            raise TelegramAPIError("Telegram bot token is not configured", requires_reconnect=True)
        return f"{TELEGRAM_API_BASE}/bot{token}/{method}"

    async def _request(self, bot_token: str, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(self._method_url(bot_token, method), json=payload or {})
        except httpx.TimeoutException as exc:
            raise TelegramAPIError("Telegram request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise TelegramAPIError("Telegram network request failed", retryable=True) from exc

        body: dict[str, Any]
        try:
            decoded = response.json()
            body = decoded if isinstance(decoded, dict) else {}
        except ValueError:
            body = {}

        if response.is_success and body.get("ok") is True:
            result = body.get("result")
            return result if isinstance(result, dict) else {}

        error_code = body.get("error_code")
        try:
            status_code = int(error_code) if error_code is not None else response.status_code
        except (TypeError, ValueError):
            status_code = response.status_code
        description = str(body.get("description") or "Telegram Bot API request failed")[:500]
        parameters = body.get("parameters") if isinstance(body.get("parameters"), dict) else {}
        retry_after = parameters.get("retry_after")
        try:
            retry_after_seconds = int(retry_after) if retry_after is not None else None
        except (TypeError, ValueError):
            retry_after_seconds = None
        reconnect = status_code in {401, 403}
        retryable = status_code == 429 or status_code >= 500
        raise TelegramAPIError(
            description,
            status_code=status_code,
            retryable=retryable,
            requires_reconnect=reconnect,
            retry_after_seconds=retry_after_seconds,
        )

    async def get_me(self, bot_token: str) -> dict[str, Any]:
        return await self._request(bot_token, "getMe")

    async def send_text(self, bot_token: str, *, chat_id: str, text: str) -> str:
        result = await self._request(
            bot_token,
            "sendMessage",
            {"chat_id": chat_id, "text": text},
        )
        message_id = result.get("message_id")
        if message_id is None:
            raise TelegramAPIError("Telegram accepted the request without returning a message ID")
        return str(message_id)


telegram_client = TelegramBotClient()
