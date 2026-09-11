from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

INSTAGRAM_API_BASE = "https://graph.instagram.com"


@dataclass(slots=True)
class InstagramAPIError(RuntimeError):
    message: str
    status_code: int | None = None
    retryable: bool = False
    requires_reconnect: bool = False
    retry_after_seconds: int | None = None

    def __str__(self) -> str:
        return self.message


def normalize_instagram_api_version(value: str) -> str:
    version = value.strip()
    if not version:
        raise InstagramAPIError("Instagram API version is not configured")
    if not version.startswith("v"):
        version = f"v{version}"
    if not version[1:].replace(".", "").isdigit():
        raise InstagramAPIError("Instagram API version is invalid")
    return version


class InstagramMessagingClient:
    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = timeout_seconds

    async def _request(
        self,
        method: str,
        path: str,
        *,
        access_token: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = access_token.strip()
        if not token:
            raise InstagramAPIError(
                "Instagram access token is not configured",
                requires_reconnect=True,
            )
        url = f"{INSTAGRAM_API_BASE}/{path.lstrip('/')}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.request(
                    method,
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    json=json,
                )
        except httpx.TimeoutException as exc:
            raise InstagramAPIError("Instagram request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise InstagramAPIError("Instagram network request failed", retryable=True) from exc

        try:
            decoded = response.json()
            body = decoded if isinstance(decoded, dict) else {}
        except ValueError:
            body = {}

        if response.is_success and "error" not in body:
            return body

        error = body.get("error") if isinstance(body.get("error"), dict) else {}
        message = str(error.get("message") or "Instagram API request failed")[:500]
        code_value = error.get("code")
        try:
            code = int(code_value) if code_value is not None else None
        except (TypeError, ValueError):
            code = None
        retry_after_value = response.headers.get("Retry-After")
        try:
            retry_after = int(retry_after_value) if retry_after_value else None
        except ValueError:
            retry_after = None
        reconnect = response.status_code in {401, 403} or code == 190
        retryable = (
            response.status_code == 429
            or response.status_code >= 500
            or code in {4, 17, 32, 613}
        )
        raise InstagramAPIError(
            message,
            status_code=response.status_code,
            retryable=retryable,
            requires_reconnect=reconnect,
            retry_after_seconds=retry_after,
        )

    async def get_me(self, access_token: str, *, api_version: str) -> dict[str, Any]:
        version = normalize_instagram_api_version(api_version)
        return await self._request(
            "GET",
            f"{version}/me?fields=id,username",
            access_token=access_token,
        )

    async def send_text(
        self,
        access_token: str,
        *,
        sender_account_id: str,
        recipient_id: str,
        text: str,
        api_version: str,
    ) -> str:
        sender = sender_account_id.strip()
        recipient = recipient_id.strip()
        message = text.strip()
        if not sender:
            raise InstagramAPIError("Instagram professional account ID is not configured")
        if not recipient:
            raise InstagramAPIError("Instagram recipient is unavailable")
        if not message:
            raise InstagramAPIError("Instagram message text is empty")
        version = normalize_instagram_api_version(api_version)
        result = await self._request(
            "POST",
            f"{version}/{sender}/messages",
            access_token=access_token,
            json={"recipient": {"id": recipient}, "message": {"text": message}},
        )
        message_id = result.get("message_id")
        if message_id is None:
            raise InstagramAPIError(
                "Instagram accepted the request without returning a message ID"
            )
        return str(message_id)


instagram_client = InstagramMessagingClient()
