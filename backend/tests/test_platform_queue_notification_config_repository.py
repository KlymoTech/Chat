"""Persistent route reads are tenant-scoped and never activate delivery."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from northstar_api.modules.platform_runtime.queue_notification_config_repository import (
    PostgresApprovedRouteRepository,
)


def factory(record):
    session = MagicMock()
    session.scalar = AsyncMock(return_value=record)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock()
    return MagicMock(return_value=session), session


@pytest.mark.asyncio
async def test_route_lookup_filters_both_tenant_and_channel():
    tenant = uuid4()
    record = SimpleNamespace(
        tenant_id=tenant, channel="email", destination_reference="approved:primary",
        revision=2, enabled=False, approved=False,
    )
    sessions, session = factory(record)
    result = await PostgresApprovedRouteRepository(sessions).get_route(tenant, "email")
    assert result.tenant_id == tenant
    assert not result.enabled
    assert not result.approved
    params = session.scalar.await_args.args[0].compile().params.values()
    assert tenant in params
    assert "email" in params


@pytest.mark.asyncio
async def test_missing_route_fails_closed():
    sessions, session = factory(None)
    result = await PostgresApprovedRouteRepository(sessions).get_route(uuid4(), "webhook")
    assert result is None
    session.scalar.assert_awaited_once()


@pytest.mark.asyncio
async def test_unsupported_channel_skips_database():
    sessions, session = factory(None)
    result = await PostgresApprovedRouteRepository(sessions).get_route(uuid4(), "sms")
    assert result is None
    session.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_corrupt_persisted_configuration_does_not_become_approved():
    tenant = uuid4()
    invalid = SimpleNamespace(tenant_id=tenant, channel="email",
                              destination_reference="https://unapproved.example",
                              revision=1, enabled=True, approved=True)
    sessions, _ = factory(invalid)
    with pytest.raises(ValueError):
        await PostgresApprovedRouteRepository(sessions).get_route(tenant, "email")
