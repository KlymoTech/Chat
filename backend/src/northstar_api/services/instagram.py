from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from northstar_api.config import get_settings


@dataclass(slots=True)
class InstagramAPIError(RuntimeError):
    message: str
    status_code: int | None = None
    meta_code: int | None = None
    retryable: bool = False
    requires_reconnect: bool = False

    def __str__(self) -> str:
        return self.message


def split_instagram_text(value: str, limit: int = 1_000) -> list[str]:
    text = value.strip()
    if not text:
        return []
    chunks: list[str] = []
    while len(text) > limit:
        boundary = text.rfind("\n", 0, limit + 1)
        if boundary < limit // 2:
            boundary = text.rfind(" ", 0, limit + 1)
        if boundary < limit // 2:
            boundary = limit
        chunk = text[:boundary].strip()
        if chunk:
            chunks.append(chunk)
        text = text[boundary:].strip()
    if text:
        chunks.append(text)
    return chunks


def _error_from_response(response: httpx.Response) -> InstagramAPIError:
    status = response.status_code
    meta_code: int | None = None
    message = "Instagram Graph API request failed"
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            raw_code = error.get("code")
            try:
                meta_code = int(raw_code) if raw_code is not None else None
            except (TypeError, ValueError):
                meta_code = None
            supplied = error.get("message")
            if isinstance(supplied, str) and supplied.strip():
                message = supplied[:500]
    reconnect = status in {401, 403} or meta_code in {102, 190}
    retryable = status == 429 or status >= 500 or meta_code in {1, 2, 4, 17, 32, 613}
    return InstagramAPIError(
        message=message,
        status_code=status,
        meta_code=meta_code,
        retryable=retryable,
        requires_reconnect=reconnect,
    )


class InstagramMessagingClient:
    def __init__(self, *, timeout_seconds: float = 15.0) -> None:
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _base() -> str:
        # The Instagram Login messaging surface is intentionally separate from
        # the Facebook Graph host used by the WhatsApp integration.
        return "https://graph.instagram.com"

    @staticmethod
    def _version() -> str:
        return get_settings().meta_graph_api_version.strip("/")

    async def account_identity(self, access_token: str, instagram_user_id: str) -> dict[str, Any]:
        if not access_token or not instagram_user_id:
            raise InstagramAPIError("Instagram access token and professional account ID are required")
        url = f"{self._base()}/{self._version()}/{instagram_user_id}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(
                    url,
                    params={"fields": "id,username"},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
        except httpx.RequestError as exc:
            raise InstagramAPIError("Instagram Graph API is temporarily unavailable", retryable=True) from exc
        if not response.is_success:
            raise _error_from_response(response)
        payload = response.json()
        if not isinstance(payload, dict) or str(payload.get("id") or "") != str(instagram_user_id):
            raise InstagramAPIError("Instagram professional account validation returned an unexpected response")
        return payload

    async def send_text(
        self,
        access_token: str,
        *,
        instagram_user_id: str,
        recipient_id: str,
        text: str,
    ) -> str:
        if not access_token or not instagram_user_id or not recipient_id:
            raise InstagramAPIError("Instagram messaging credentials or recipient are unavailable")
        if not text.strip():
            raise InstagramAPIError("Instagram message text is empty")
        url = f"{self._base()}/{self._version()}/{instagram_user_id}/messages"
        body = {"recipient": {"id": recipient_id}, "message": {"text": text}}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    url,
                    json=body,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
        except httpx.RequestError as exc:
            raise InstagramAPIError("Instagram Graph API is temporarily unavailable", retryable=True) from exc
        if not response.is_success:
            raise _error_from_response(response)
        payload = response.json()
        if not isinstance(payload, dict):
            raise InstagramAPIError("Instagram send response was invalid", retryable=True)
        message_id = str(payload.get("message_id") or "")
        if not message_id:
            raise InstagramAPIError("Instagram did not return a message ID", retryable=True)
        return message_id


instagram_client = InstagramMessagingClient()
