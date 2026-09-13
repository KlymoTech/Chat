from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from northstar_api.database import Base
from northstar_api.lead_crm.connectors import CRMFieldDefinition
from northstar_api.lead_crm.crm_provisioning import (
    build_default_mapping,
    connection_readiness,
    managed_provider_catalog,
    one_click_configuration,
    provision_connection,
)
from northstar_api.lead_crm.domain import CRMProvider
from northstar_api.lead_crm.models import CRMConnection, CRMFieldMapping, CRMRoute
from northstar_api.lead_crm.workspace_scope import WorkspaceCRMConnection, WorkspaceCRMRoute
from northstar_api.models import OutboxEvent, Tenant, Workspace


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as value:
        yield value
    await engine.dispose()


def test_zoho_default_mapping_supplies_mandatory_lead_fields() -> None:
    fields = [
        CRMFieldDefinition("Last_Name", "Last Name", "text", required=True),
        CRMFieldDefinition("Company", "Company", "text", required=True),
        CRMFieldDefinition("Email", "Email", "email"),
    ]
    mapping, validation = build_default_mapping(CRMProvider.ZOHO, fields)
    targets = {item["target"] for item in mapping["fields"]}
    assert {"Last_Name", "Company", "Email"} <= targets
    assert validation["valid"] is True
    assert validation["missingRequiredTargets"] == []


def test_salesforce_mapping_blocks_unknown_required_fields() -> None:
    fields = [
        CRMFieldDefinition("LastName", "Last Name", "text", required=True),
        CRMFieldDefinition("Company", "Company", "text", required=True),
        CRMFieldDefinition("Required_Custom__c", "Required Custom", "text", required=True),
    ]
    _, validation = build_default_mapping(CRMProvider.SALESFORCE, fields)
    assert validation["valid"] is False
    assert validation["missingRequiredTargets"] == ["Required_Custom__c"]


def test_provider_configuration_uses_safe_current_defaults() -> None:
    zoho = one_click_configuration(
        CRMProvider.ZOHO,
        environment="production",
        region="in",
        resource_url=None,
        azure_tenant_id=None,
    )
    assert zoho["accountsUrl"] == "https://accounts.zoho.in"
    assert zoho["apiVersion"] == "v8"
    assert "ZohoCRM.modules.leads.ALL" in zoho["oauthScopes"]

    salesforce = one_click_configuration(
        CRMProvider.SALESFORCE,
        environment="sandbox",
        region=None,
        resource_url=None,
        azure_tenant_id=None,
    )
    assert salesforce == {
        "managedOAuth": True,
        "environment": "sandbox",
        "apiVersion": "v65.0",
        "pkce": True,
    }

    dynamics = one_click_configuration(
        CRMProvider.DYNAMICS365,
        environment="production",
        region=None,
        resource_url="https://contoso.crm.dynamics.com/",
        azure_tenant_id="common",
    )
    assert dynamics["resourceUrl"] == "https://contoso.crm.dynamics.com"
    assert dynamics["pkce"] is True


def test_provider_catalog_does_not_claim_unconfigured_oauth_apps() -> None:
    settings = SimpleNamespace(
        crm_zoho_client_id=None,
        crm_zoho_client_secret=None,
        crm_salesforce_client_id=None,
        crm_salesforce_client_secret=None,
        crm_hubspot_client_id=None,
        crm_hubspot_client_secret=None,
        crm_dynamics365_client_id=None,
        crm_dynamics365_client_secret=None,
        crm_pipedrive_client_id=None,
        crm_pipedrive_client_secret=None,
    )
    catalog = {item["id"]: item for item in managed_provider_catalog(settings)}
    assert catalog["zoho"]["configured"] is False
    assert catalog["salesforce"]["configured"] is False
    assert catalog["freshsales"]["configured"] is True
    assert catalog["generic_rest"]["configured"] is True


async def test_generic_rest_provisioning_activates_mapping_route_autosync_and_backfill(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from northstar_api.lead_crm import crm_provisioning

    tenant = Tenant(slug=f"crm-one-click-{uuid4().hex}", name="CRM one-click")
    session.add(tenant)
    await session.flush()
    workspace = Workspace(
        tenant_id=tenant.id,
        name="Sales",
        slug=f"sales-{uuid4().hex[:8]}",
    )
    session.add(workspace)
    await session.flush()
    connection = CRMConnection(
        tenant_id=tenant.id,
        provider=CRMProvider.GENERIC_REST.value,
        name="Customer CRM",
        status="healthy",
        credentials_encrypted=b"encrypted-fixture",
        configuration_json={
            "baseUrl": "https://crm.example.com/api",
            "healthPath": "/health",
            "upsertPath": "/leads/upsert",
            "getPath": "/leads/{id}",
            "updatePath": "/leads/{id}",
            "externalIdPath": "$.id",
            "readBackIdPath": "id",
            "directConnect": True,
        },
    )
    session.add(connection)
    await session.flush()
    monkeypatch.setattr(
        crm_provisioning,
        "get_settings",
        lambda: SimpleNamespace(kafka_enabled=True, background_dispatch_enabled=True),
    )

    result = await provision_connection(
        session,
        tenant_id=tenant.id,
        workspace_id=workspace.id,
        connection=connection,
        credentials={"auth_type": "none"},
    )
    await session.flush()

    assert result.readiness.ready is True
    assert result.schema_field_count == 0
    mapping = await session.scalar(
        select(CRMFieldMapping).where(CRMFieldMapping.connection_id == connection.id)
    )
    assert mapping is not None and mapping.status == "active"
    assert mapping.validation_json["valid"] is True
    binding = await session.scalar(
        select(WorkspaceCRMConnection).where(
            WorkspaceCRMConnection.workspace_id == workspace.id,
            WorkspaceCRMConnection.connection_id == connection.id,
        )
    )
    assert binding is not None
    assert binding.auto_sync_new_leads is True and binding.auto_sync_updates is True
    route = await session.scalar(
        select(CRMRoute)
        .join(WorkspaceCRMRoute, WorkspaceCRMRoute.route_id == CRMRoute.id)
        .where(WorkspaceCRMRoute.workspace_id == workspace.id)
    )
    assert route is not None and route.enabled is True
    assert str(connection.id) in route.actions_json["connectionIds"]
    event = await session.scalar(
        select(OutboxEvent).where(
            OutboxEvent.event_type == "crm.connection.backfill.requested.v1",
            OutboxEvent.aggregate_id == str(connection.id),
        )
    )
    assert event is not None
    assert event.payload["workspaceId"] == str(workspace.id)

    readiness = await connection_readiness(
        session,
        tenant_id=tenant.id,
        workspace_id=workspace.id,
        connection=connection,
    )
    assert readiness.ready is True
    assert readiness.live_certified is False
