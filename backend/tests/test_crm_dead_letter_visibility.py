from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from northstar_api.database import Base
from northstar_api.lead_crm.models import CRMConnection, CRMDelivery, IntegrationDeadLetter
from northstar_api.models import Agent, Lead, Tenant, Workspace
from northstar_api.routers.crm_dead_letters import list_crm_dead_letters
from northstar_api.security import Principal
from northstar_api.models import Role, WorkspaceRole


@pytest.fixture
async def dead_letter_case() -> AsyncIterator[
    tuple[AsyncSession, Principal, CRMConnection, IntegrationDeadLetter, IntegrationDeadLetter]
]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(slug=f"dlq-{uuid4().hex}", name="Dead-letter tenant")
        session.add(tenant)
        await session.flush()

        workspace = Workspace(
            tenant_id=tenant.id,
            name="Primary workspace",
            slug=f"primary-{uuid4().hex[:8]}",
        )
        other_workspace = Workspace(
            tenant_id=tenant.id,
            name="Other workspace",
            slug=f"other-{uuid4().hex[:8]}",
        )
        session.add_all([workspace, other_workspace])
        await session.flush()

        agent = Agent(tenant_id=tenant.id, workspace_id=workspace.id, name="Primary agent")
        other_agent = Agent(
            tenant_id=tenant.id,
            workspace_id=other_workspace.id,
            name="Other agent",
        )
        session.add_all([agent, other_agent])
        await session.flush()

        lead = Lead(
            tenant_id=tenant.id,
            workspace_id=workspace.id,
            agent_id=agent.id,
            name="Primary lead",
            status="new",
            consent=True,
            fields_json={},
        )
        other_lead = Lead(
            tenant_id=tenant.id,
            workspace_id=other_workspace.id,
            agent_id=other_agent.id,
            name="Other lead",
            status="new",
            consent=True,
            fields_json={},
        )
        session.add_all([lead, other_lead])
        await session.flush()

        connection = CRMConnection(
            tenant_id=tenant.id,
            public_id=f"crm_{uuid4().hex}",
            provider="generic_rest",
            name="Primary CRM",
            status="healthy",
            configuration_json={},
        )
        session.add(connection)
        await session.flush()

        delivery = CRMDelivery(
            tenant_id=tenant.id,
            lead_id=lead.id,
            connection_id=connection.id,
            provider="generic_rest",
            operation="upsert",
            idempotency_key=f"primary-{uuid4().hex}",
            status="dead_letter",
        )
        other_delivery = CRMDelivery(
            tenant_id=tenant.id,
            lead_id=other_lead.id,
            connection_id=connection.id,
            provider="generic_rest",
            operation="upsert",
            idempotency_key=f"other-{uuid4().hex}",
            status="dead_letter",
        )
        session.add_all([delivery, other_delivery])
        await session.flush()

        primary_dead_letter = IntegrationDeadLetter(
            tenant_id=tenant.id,
            delivery_id=delivery.id,
            status="open",
            reason_code="network_error",
            reason_message="Provider timed out",
            metadata_json={"secretDiagnostic": "must-not-be-returned", "httpStatus": 504},
        )
        other_dead_letter = IntegrationDeadLetter(
            tenant_id=tenant.id,
            delivery_id=other_delivery.id,
            status="open",
            reason_code="rate_limit_error",
            reason_message="Provider rate limit exhausted",
            metadata_json={"secretDiagnostic": "other-workspace"},
        )
        session.add_all([primary_dead_letter, other_dead_letter])
        await session.commit()

        principal = Principal(
            user_id=uuid4(),
            tenant_id=tenant.id,
            role=Role.MEMBER,
            token_id="dead-letter-test",
            workspace_id=workspace.id,
            workspace_role=WorkspaceRole.MANAGER,
            permissions=frozenset({"crm.view"}),
        )
        yield session, principal, connection, primary_dead_letter, other_dead_letter

    await engine.dispose()


async def test_dead_letter_list_is_workspace_scoped_and_safe(dead_letter_case) -> None:
    session, principal, connection, primary_dead_letter, other_dead_letter = dead_letter_case

    rows = await list_crm_dead_letters(
        principal=principal,
        session=session,
        connection_id=None,
        dead_letter_status="open",
    )

    assert [row.id for row in rows] == [primary_dead_letter.id]
    assert other_dead_letter.id not in {row.id for row in rows}
    assert rows[0].connection_id == connection.id
    assert rows[0].reason_code == "network_error"
    assert "metadata_json" not in rows[0].model_dump()
    assert "metadata" not in rows[0].model_dump()


async def test_dead_letter_filters_status_and_connection(dead_letter_case) -> None:
    session, principal, connection, primary_dead_letter, _ = dead_letter_case
    primary_dead_letter.status = "resolved"
    primary_dead_letter.resolved_at = datetime.now(UTC)
    await session.commit()

    open_rows = await list_crm_dead_letters(
        principal=principal,
        session=session,
        connection_id=connection.id,
        dead_letter_status="open",
    )
    resolved_rows = await list_crm_dead_letters(
        principal=principal,
        session=session,
        connection_id=connection.id,
        dead_letter_status="resolved",
    )
    all_rows = await list_crm_dead_letters(
        principal=principal,
        session=session,
        connection_id=connection.id,
        dead_letter_status="all",
    )

    assert open_rows == []
    assert [row.id for row in resolved_rows] == [primary_dead_letter.id]
    assert [row.id for row in all_rows] == [primary_dead_letter.id]
