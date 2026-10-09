"""Real ASGI/SQLite contracts used by the redesigned dashboard and inbox.

Only test records are seeded directly. Requests use the application's actual
routes, authentication, authorization, serialization, and database queries.
No channel delivery or paid AI provider is called.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from northstar_api.database import SessionFactory
from northstar_api.models import Conversation, ConversationState


async def make_scope(client: AsyncClient, headers: dict[str, str]) -> dict:
    suffix = uuid4().hex[:12]
    response = await client.post(
        "/api/v1/workspaces",
        headers=headers,
        json={"name": f"Dashboard review {suffix}", "slug": f"dashboard-review-{suffix}"},
    )
    assert response.status_code == 201, response.text
    workspace = response.json()
    scoped = {**headers, "X-Workspace-ID": workspace["id"]}
    response = await client.post(
        "/api/v1/agents",
        headers=scoped,
        json={"name": f"Review assistant {suffix}", "description": "Isolated dashboard fixture"},
    )
    assert response.status_code == 201, response.text
    return {"workspace": workspace, "headers": scoped, "agent": response.json()}


async def seed_conversations(scope: dict, states: list[tuple[ConversationState, int]]) -> list[str]:
    now = datetime.now(UTC)
    ids: list[str] = []
    async with SessionFactory() as session:
        for state, minutes_ago in states:
            identifier = uuid4()
            ids.append(str(identifier))
            session.add(
                Conversation(
                    id=identifier,
                    tenant_id=UUID(scope["workspace"]["tenantId"]),
                    workspace_id=UUID(scope["workspace"]["id"]),
                    agent_id=UUID(scope["agent"]["id"]),
                    visitor_name=f"Review visitor {identifier.hex[:8]}",
                    state=state,
                    started_at=now - timedelta(minutes=minutes_ago),
                    updated_at=now - timedelta(minutes=minutes_ago),
                )
            )
        await session.commit()
    return ids


async def test_attention_filter_applies_before_pagination(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    scope = await make_scope(client, auth_headers)
    ids = await seed_conversations(
        scope,
        [
            *[(ConversationState.RESOLVED, minute) for minute in range(51)],
            (ConversationState.OPEN, 60),
            (ConversationState.OPEN, 70),
            (ConversationState.ESCALATED, 65),
        ],
    )
    unfiltered = await client.get("/api/v1/conversations", headers=scope["headers"])
    assert unfiltered.status_code == 200, unfiltered.text
    assert unfiltered.json()["total"] == 54
    assert len(unfiltered.json()["items"]) == 50
    assert all(item["state"] == "resolved" for item in unfiltered.json()["items"])

    for state, expected in [("open", ids[51:53]), ("escalated", ids[53:])]:
        response = await client.get(
            "/api/v1/conversations",
            headers=scope["headers"],
            params={"state": state, "page": 1, "page_size": 3},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert [item["id"] for item in payload["items"]] == expected
        assert payload["total"] == len(expected)
        assert payload["page"] == 1 and payload["pageSize"] == 3
        assert all(item["state"] == state for item in payload["items"])
        assert all(item["workspaceId"] == scope["workspace"]["id"] for item in payload["items"])


async def test_off_page_detail_and_other_workspace_isolation(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    first = await make_scope(client, auth_headers)
    second = await make_scope(client, auth_headers)
    [identifier] = await seed_conversations(first, [(ConversationState.OPEN, 60)])
    detail = await client.get(f"/api/v1/conversations/{identifier}", headers=first["headers"])
    assert detail.status_code == 200, detail.text
    assert detail.json()["id"] == identifier
    assert detail.json()["agentId"] == first["agent"]["id"]
    assert isinstance(detail.json()["messages"], list)

    forbidden = await client.get(f"/api/v1/conversations/{identifier}", headers=second["headers"])
    assert forbidden.status_code == 404, forbidden.text
    for state in ("open", "escalated"):
        response = await client.get(
            "/api/v1/conversations", headers=second["headers"], params={"state": state}
        )
        assert response.status_code == 200, response.text
        assert response.json()["items"] == []
    sources = await client.get(f"/api/v1/agents/{first['agent']['id']}/knowledge", headers=second["headers"])
    assert sources.status_code == 404, sources.text


@pytest.mark.parametrize("days", [7, 30])
async def test_dashboard_period_metrics_are_scoped_real_data(
    client: AsyncClient, auth_headers: dict[str, str], days: int
) -> None:
    scope = await make_scope(client, auth_headers)
    await seed_conversations(
        scope,
        [
            (ConversationState.OPEN, 60),
            (ConversationState.RESOLVED, 120),
            (ConversationState.OPEN, 15 * 24 * 60),
        ],
    )
    response = await client.get("/api/v1/analytics/summary", headers=scope["headers"], params={"days": days})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["conversations"] == (2 if days == 7 else 3)
    assert 0 <= payload["resolutionRate"] <= 100
    assert payload["avgResponseSeconds"] >= 0
    # Existing API uses daily weekly buckets and four-day monthly buckets.
    assert len(payload["chart"]) == (7 if days == 7 else 8)
    assert payload["period"] == f"Last {days} days"
    assert sum(item["conversations"] for item in payload["chart"]) == payload["conversations"]
    assert sum(item["resolved"] for item in payload["chart"]) == 1
    assert all({"label", "conversations", "resolved"} <= item.keys() for item in payload["chart"])


async def test_dashboard_agents_knowledge_and_connection_shapes(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    scope = await make_scope(client, auth_headers)
    agents = await client.get("/api/v1/agents", headers=scope["headers"])
    assert agents.status_code == 200, agents.text
    assert [agent["id"] for agent in agents.json()] == [scope["agent"]["id"]]
    # Default website support agents are active; education/WhatsApp use draft.
    assert agents.json()[0]["status"] == "active"
    sources = await client.get(f"/api/v1/agents/{scope['agent']['id']}/knowledge", headers=scope["headers"])
    assert sources.status_code == 200, sources.text
    assert sources.json() == []
    connections = await client.get("/api/v1/integrations", headers=scope["headers"])
    assert connections.status_code == 200, connections.text
    assert isinstance(connections.json(), list)
    assert all(isinstance(item["connected"], bool) for item in connections.json())


@pytest.mark.parametrize(
    "path", ["agents", "analytics/summary?days=7", "conversations?state=open", "integrations"]
)
async def test_dashboard_rejects_missing_authentication_and_unknown_workspace(
    client: AsyncClient, auth_headers: dict[str, str], path: str
) -> None:
    anonymous = await client.get(f"/api/v1/{path}")
    assert anonymous.status_code == 401, anonymous.text
    unknown = await client.get(f"/api/v1/{path}", headers={**auth_headers, "X-Workspace-ID": str(uuid4())})
    assert unknown.status_code == 403, unknown.text
