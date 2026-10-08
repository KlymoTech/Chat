"""Desired-state API tests: persistent configuration is authoritative."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from northstar_api.modules.platform_runtime.contracts import PlatformSpec
from northstar_api.modules.platform_runtime.control_plane import spec_digest
from northstar_api.modules.super_admin.api.runtime import get_persisted_desired_state


@pytest.mark.asyncio
async def test_absent_persisted_state_is_not_inferred_from_environment() -> None:
    session = MagicMock()
    session.scalar = AsyncMock(return_value=None)
    response = await get_persisted_desired_state(None, session, "production")
    assert response["source"] == "database"
    assert response["state"] == "unconfigured"
    assert response["desired"] is None


@pytest.mark.asyncio
async def test_persisted_revision_is_verified() -> None:
    spec = PlatformSpec()
    record = MagicMock(
        configuration_json=spec.model_dump(mode="json"),
        environment="development",
        revision=1,
        digest=spec_digest(spec),
    )
    session = MagicMock()
    session.scalar = AsyncMock(return_value=record)
    response = await get_persisted_desired_state(None, session, "development")
    assert response["state"] == "persisted"
    assert response["digest"] == spec_digest(spec)


@pytest.mark.asyncio
async def test_digest_tampering_is_rejected() -> None:
    spec = PlatformSpec()
    record = MagicMock(
        configuration_json=spec.model_dump(mode="json"),
        environment="development",
        revision=1,
        digest="0" * 64,
    )
    session = MagicMock()
    session.scalar = AsyncMock(return_value=record)
    with pytest.raises(HTTPException) as exception:
        await get_persisted_desired_state(None, session, "development")
    assert exception.value.status_code == 409
