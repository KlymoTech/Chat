from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import structlog
from redis.exceptions import RedisError

from northstar_api.services.rate_limit import redis_services

logger = structlog.get_logger(__name__)
_CACHE_TTL_SECONDS = 300


def _workspace_key(workspace_id: UUID) -> str:
    return f"northstar:brand:workspace:{workspace_id}"


def _domain_key(hostname: str) -> str:
    return f"northstar:brand:domain:{hostname.strip().lower().rstrip('.')}"


async def cached_workspace_brand(workspace_id: UUID) -> dict[str, Any] | None:
    try:
        raw = await redis_services.client.get(_workspace_key(workspace_id))
    except RedisError as exc:
        logger.warning("brand_cache_read_unavailable", scope="workspace", error=type(exc).__name__)
        return None
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


async def cache_workspace_brand(workspace_id: UUID, payload: dict[str, Any]) -> None:
    try:
        await redis_services.client.set(
            _workspace_key(workspace_id),
            json.dumps(payload, separators=(",", ":")),
            ex=_CACHE_TTL_SECONDS,
        )
    except RedisError as exc:
        logger.warning("brand_cache_write_unavailable", scope="workspace", error=type(exc).__name__)


async def cached_domain_brand(hostname: str) -> dict[str, Any] | None:
    try:
        raw = await redis_services.client.get(_domain_key(hostname))
    except RedisError as exc:
        logger.warning("brand_cache_read_unavailable", scope="domain", error=type(exc).__name__)
        return None
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


async def cache_domain_brand(hostname: str, payload: dict[str, Any]) -> None:
    try:
        await redis_services.client.set(
            _domain_key(hostname),
            json.dumps(payload, separators=(",", ":")),
            ex=_CACHE_TTL_SECONDS,
        )
    except RedisError as exc:
        logger.warning("brand_cache_write_unavailable", scope="domain", error=type(exc).__name__)


async def invalidate_brand_cache(
    workspace_id: UUID,
    *,
    hostnames: list[str] | tuple[str, ...] = (),
    version: int | None = None,
) -> None:
    keys = [_workspace_key(workspace_id), *[_domain_key(hostname) for hostname in hostnames if hostname]]
    event = {
        "workspaceId": str(workspace_id),
        "version": version,
        "domains": [hostname for hostname in hostnames if hostname],
    }
    try:
        if keys:
            await redis_services.client.delete(*keys)
        await redis_services.client.publish("northstar:brand-updated", json.dumps(event, separators=(",", ":")))
    except RedisError as exc:
        logger.warning("brand_cache_invalidation_unavailable", error=type(exc).__name__)
