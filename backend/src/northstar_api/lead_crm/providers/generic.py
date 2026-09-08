from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import urljoin

import httpx

from northstar_api.lead_crm.connectors import (
    CRMCapabilities,
    CRMConnectionContext,
    CRMConnector,
    CRMDeliveryResult,
    CRMError,
    CRMHealthResult,
)
from northstar_api.lead_crm.domain import CRMOperation, CRMProvider, IntegrationHealthStatus, NormalizedCRMErrorCode
from northstar_api.lead_crm.safe_http import UnsafeOutboundCRMURL, request_public


def _extract_path(value: Any, path: str | None) -> Any:
    if not path:
        return None
    current = value
    for part in path.removeprefix("$.").split("."):
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else None
        else:
            return None
    return current


def _headers(context: CRMConnectionContext) -> dict[str, str]:
    configuration = context.configuration
    credentials = context.credentials
    headers = {str(k): str(v) for k, v in (configuration.get("headers") or {}).items()}
    auth_type = str((configuration.get("auth") or {}).get("type", "NONE")).upper()
    if auth_type == "BEARER":
        token = credentials.get("token") or credentials.get("access_token")
        if not token:
            raise CRMError(NormalizedCRMErrorCode.AUTHENTICATION_ERROR, "Bearer credential is missing", requires_reconnect=True)
        headers["Authorization"] = f"Bearer {token}"
    elif auth_type == "BASIC":
        username = credentials.get("username")
        password = credentials.get("password")
        if not username or password is None:
            raise CRMError(NormalizedCRMErrorCode.AUTHENTICATION_ERROR, "Basic credentials are missing", requires_reconnect=True)
        headers["Authorization"] = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
    elif auth_type == "API_KEY_HEADER":
        name = str((configuration.get("auth") or {}).get("name") or "X-API-Key")
        key = credentials.get("api_key")
        if not key:
            raise CRMError(NormalizedCRMErrorCode.AUTHENTICATION_ERROR, "API key is missing", requires_reconnect=True)
        headers[name] = str(key)
    elif auth_type not in {"NONE", ""}:
        raise CRMError(NormalizedCRMErrorCode.CONFIGURATION_ERROR, f"Unsupported generic auth type: {auth_type}")
    headers.setdefault("Content-Type", "application/json")
    headers.setdefault("Accept", "application/json")
    return headers


def _classify_http(status: int, *, retry_after: int | None = None) -> CRMError:
    if status in {401, 403}:
        return CRMError(
            NormalizedCRMErrorCode.AUTHENTICATION_ERROR if status == 401 else NormalizedCRMErrorCode.AUTHORIZATION_ERROR,
            "CRM rejected authentication or authorization",
            requires_reconnect=status == 401,
            http_status=status,
        )
    if status == 429:
        return CRMError(
            NormalizedCRMErrorCode.RATE_LIMIT_ERROR,
            "CRM rate limit reached",
            retryable=True,
            http_status=status,
            retry_after_seconds=retry_after,
        )
    if status in {408, 425} or status >= 500:
        return CRMError(
            NormalizedCRMErrorCode.PROVIDER_UNAVAILABLE,
            "CRM provider is temporarily unavailable",
            retryable=True,
            http_status=status,
        )
    return CRMError(NormalizedCRMErrorCode.VALIDATION_ERROR, "CRM rejected the request", http_status=status)


class GenericRESTConnector(CRMConnector):
    provider = CRMProvider.GENERIC_REST
    capabilities = CRMCapabilities(schema_discovery=False, create=True, update=True, upsert=True, read_back=True)

    def _url(self, context: CRMConnectionContext, path_key: str, default_path: str = "") -> str:
        base = str(context.configuration.get("baseUrl") or "").rstrip("/") + "/"
        path = str(context.configuration.get(path_key) or default_path).lstrip("/")
        return urljoin(base, path)

    async def _request(
        self,
        context: CRMConnectionContext,
        *,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        content: bytes | None = None,
        headers_override: dict[str, str] | None = None,
    ) -> httpx.Response:
        headers = headers_override or _headers(context)
        if idempotency_key:
            headers[str(context.configuration.get("idempotencyHeader") or "Idempotency-Key")] = idempotency_key
        timeout = min(max(float(context.configuration.get("timeoutSeconds", 15)), 1), 60)
        try:
            response = await request_public(
                method,
                url,
                headers=headers,
                json_body=payload if content is None else None,
                content=content,
                timeout_seconds=timeout,
            )
        except UnsafeOutboundCRMURL as exc:
            raise CRMError(NormalizedCRMErrorCode.CONFIGURATION_ERROR, "Generic CRM destination is not a permitted public HTTPS URL") from exc
        except httpx.TimeoutException as exc:
            raise CRMError(NormalizedCRMErrorCode.TIMEOUT, "CRM request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise CRMError(NormalizedCRMErrorCode.NETWORK_ERROR, "CRM network request failed", retryable=True) from exc
        if 300 <= response.status_code < 400:
            raise CRMError(NormalizedCRMErrorCode.CONFIGURATION_ERROR, "Generic CRM redirects are not followed")
        success_codes = {int(code) for code in context.configuration.get("successStatusCodes", [200, 201, 202, 204])}
        if response.status_code not in success_codes:
            retry_after = None
            raw_retry = response.headers.get("Retry-After")
            if raw_retry and raw_retry.isdigit():
                retry_after = int(raw_retry)
            raise _classify_http(response.status_code, retry_after=retry_after)
        return response

    async def health_check(self, context: CRMConnectionContext) -> CRMHealthResult:
        started = time.monotonic()
        health_url = self._url(context, "healthPath", "")
        try:
            await self._request(context, method="GET", url=health_url)
            return CRMHealthResult(
                status=IntegrationHealthStatus.HEALTHY,
                checks={"credentials": "up", "api": "up"},
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        except CRMError as exc:
            status = IntegrationHealthStatus.AUTH_REQUIRED if exc.requires_reconnect else IntegrationHealthStatus.UNHEALTHY
            return CRMHealthResult(
                status=status,
                checks={"credentials": "down" if exc.requires_reconnect else "unknown", "api": "down"},
                latency_ms=int((time.monotonic() - started) * 1000),
                details={"error": exc.code.value},
            )

    async def create_lead(
        self, context: CRMConnectionContext, payload: dict[str, Any], *, idempotency_key: str
    ) -> CRMDeliveryResult:
        url = self._url(context, "createPath", str(context.configuration.get("path") or ""))
        method = str(context.configuration.get("method") or "POST")
        response = await self._request(context, method=method, url=url, payload=payload, idempotency_key=idempotency_key)
        body: Any = None
        if response.content:
            try:
                body = response.json()
            except ValueError:
                body = None
        external_id = _extract_path(body, context.configuration.get("externalIdPath"))
        return CRMDeliveryResult(
            accepted=True,
            operation=CRMOperation.CREATE,
            external_record_id=str(external_id) if external_id is not None else None,
            http_status=response.status_code,
            provider_request_id=response.headers.get("X-Request-ID") or response.headers.get("Request-Id"),
        )

    async def update_lead(
        self,
        context: CRMConnectionContext,
        external_id: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> CRMDeliveryResult:
        template = str(context.configuration.get("updatePath") or "")
        if not template:
            raise CRMError(NormalizedCRMErrorCode.CONFIGURATION_ERROR, "Generic CRM updatePath is not configured")
        url = self._url(context, "updatePath").replace("{id}", external_id)
        response = await self._request(context, method="PATCH", url=url, payload=payload, idempotency_key=idempotency_key)
        return CRMDeliveryResult(True, CRMOperation.UPDATE, external_id, response.status_code)

    async def upsert_lead(
        self, context: CRMConnectionContext, payload: dict[str, Any], *, idempotency_key: str
    ) -> CRMDeliveryResult:
        if context.configuration.get("upsertPath"):
            url = self._url(context, "upsertPath")
            response = await self._request(context, method="POST", url=url, payload=payload, idempotency_key=idempotency_key)
            body = response.json() if response.content else None
            external_id = _extract_path(body, context.configuration.get("externalIdPath"))
            return CRMDeliveryResult(
                True,
                CRMOperation.UPSERT,
                str(external_id) if external_id is not None else None,
                response.status_code,
            )
        created = await self.create_lead(context, payload, idempotency_key=idempotency_key)
        return CRMDeliveryResult(
            created.accepted,
            CRMOperation.UPSERT,
            created.external_record_id,
            created.http_status,
            created.provider_code,
            created.provider_request_id,
        )

    async def get_lead(self, context: CRMConnectionContext, external_id: str) -> dict[str, Any]:
        template = str(context.configuration.get("getPath") or "")
        if not template:
            raise CRMError(NormalizedCRMErrorCode.CONFIGURATION_ERROR, "Generic CRM getPath is not configured")
        url = self._url(context, "getPath").replace("{id}", external_id)
        response = await self._request(context, method="GET", url=url)
        try:
            value = response.json()
        except ValueError as exc:
            raise CRMError(NormalizedCRMErrorCode.VALIDATION_ERROR, "CRM returned a non-JSON record") from exc
        if not isinstance(value, dict):
            raise CRMError(NormalizedCRMErrorCode.VALIDATION_ERROR, "CRM returned an invalid record")
        return value


class GenericWebhookConnector(GenericRESTConnector):
    provider = CRMProvider.GENERIC_WEBHOOK
    capabilities = CRMCapabilities(create=True, update=False, upsert=True, read_back=False, inbound_webhooks=False)

    async def create_lead(
        self, context: CRMConnectionContext, payload: dict[str, Any], *, idempotency_key: str
    ) -> CRMDeliveryResult:
        url = self._url(context, "path", "")
        secret = str(context.credentials.get("webhook_secret") or "")
        if not secret:
            raise CRMError(NormalizedCRMErrorCode.AUTHENTICATION_ERROR, "Webhook signing secret is missing", requires_reconnect=True)
        timestamp = str(int(time.time()))
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str).encode()
        signature = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        headers = _headers(context)
        headers.update(
            {
                "X-Northstar-Timestamp": timestamp,
                "X-Northstar-Signature": f"sha256={signature}",
                "X-Northstar-Event-ID": idempotency_key,
                "Idempotency-Key": idempotency_key,
            }
        )
        response = await self._request(
            context,
            method="POST",
            url=url,
            content=body,
            headers_override=headers,
            idempotency_key=idempotency_key,
        )
        return CRMDeliveryResult(
            accepted=True,
            operation=CRMOperation.UPSERT,
            http_status=response.status_code,
            provider_request_id=response.headers.get("X-Request-ID"),
        )
