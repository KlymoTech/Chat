from __future__ import annotations

from uuid import UUID, uuid4

from httpx import AsyncClient

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.audit import record_audit_event, record_integration_audit, redact_audit_payload


def test_audit_redaction_is_recursive_and_does_not_hide_usage_fields() -> None:
    value = redact_audit_payload(
        {
            "password": "secret-password",
            "accessToken": "secret-token",
            "nested": {"client_secret": "client-secret", "tokensMonthly": 1234},
            "items": [{"apiKey": "nsk_live_secret"}, {"safe": "visible"}],
        }
    )
    assert value["password"] == "[REDACTED]"
    assert value["accessToken"] == "[REDACTED]"
    assert value["nested"]["client_secret"] == "[REDACTED]"
    assert value["nested"]["tokensMonthly"] == 1234
    assert value["items"][0]["apiKey"] == "[REDACTED]"
    assert value["items"][1]["safe"] == "visible"


async def _workspace_scope(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> tuple[UUID, UUID]:
    response = await client.get("/api/v1/workspace", headers=auth_headers)
    assert response.status_code == 200, response.text
    return UUID(response.json()["tenantId"]), UUID(response.json()["id"])


async def test_authenticated_mutation_is_recorded_and_filterable(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    tenant_id, workspace_id = await _workspace_scope(client, auth_headers)
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text

    changed = await client.patch(
        "/api/v1/workspace",
        headers=auth_headers,
        json={"name": workspace.json()["name"]},
    )
    assert changed.status_code == 200, changed.text

    response = await client.get(
        "/api/v1/audit/events?category=workspace&action=workspace.patch&search=%2Fworkspace",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    events = response.json()
    event = next(item for item in events if item["entityId"] == "/workspace")
    assert UUID(event["tenantId"]) == tenant_id
    assert UUID(event["workspaceId"]) == workspace_id
    assert event["category"] == "workspace"
    assert event["severity"] == "info"
    assert event["outcome"] == "success"
    assert event["metadata"]["method"] == "PATCH"
    assert event["metadata"]["statusCode"] == 200
    assert event["metadata"]["credentialType"] == "session"
    serialized = str(event)
    assert "Authorization" not in serialized
    assert auth_headers["Authorization"] not in serialized


async def test_audit_api_is_workspace_scoped_but_legacy_integration_view_is_preserved(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    tenant_id, workspace_id = await _workspace_scope(client, auth_headers)
    outside_workspace = uuid4()
    marker = uuid4().hex

    async with SessionFactory() as session:
        record_audit_event(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            actor_user_id=None,
            action="workspace.test.visible",
            entity_type="workspace",
            entity_id=f"visible-{marker}",
            category="workspace",
        )
        record_audit_event(
            session,
            tenant_id=tenant_id,
            workspace_id=None,
            actor_user_id=None,
            action="security.test.tenant",
            entity_type="security",
            entity_id=f"tenant-{marker}",
            category="security",
        )
        record_integration_audit(
            session,
            tenant_id=tenant_id,
            workspace_id=outside_workspace,
            actor_user_id=None,
            action="integration.test.outside",
            entity_type="crm_connection",
            entity_id=f"outside-{marker}",
            before={"accessToken": "must-not-leak"},
            after={"status": "healthy"},
        )
        await session.commit()

    scoped = await client.get(f"/api/v1/audit/events?search={marker}", headers=auth_headers)
    assert scoped.status_code == 200, scoped.text
    scoped_ids = {item["entityId"] for item in scoped.json()}
    assert f"visible-{marker}" in scoped_ids
    assert f"tenant-{marker}" in scoped_ids
    assert f"outside-{marker}" not in scoped_ids

    legacy = await client.get(
        f"/api/v1/integration-audit?entity_id=outside-{marker}",
        headers=auth_headers,
    )
    assert legacy.status_code == 200, legacy.text
    assert len(legacy.json()) == 1
    assert legacy.json()[0]["entity_id"] == f"outside-{marker}"
    assert legacy.json()[0]["before"]["accessToken"] == "[REDACTED]"


async def test_audit_export_is_csv_safe_and_api_keys_cannot_view_audit(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    tenant_id, workspace_id = await _workspace_scope(client, auth_headers)
    formula_id = f"=HYPERLINK(\"https://invalid.test/{uuid4().hex}\")"
    async with SessionFactory() as session:
        record_audit_event(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            actor_user_id=None,
            action="workspace.export.test",
            entity_type="workspace",
            entity_id=formula_id,
            category="workspace",
        )
        await session.commit()

    export = await client.get(
        "/api/v1/audit/export?category=workspace&limit=5000",
        headers=auth_headers,
    )
    assert export.status_code == 200, export.text
    assert export.headers["content-type"].startswith("text/csv")
    assert "northstar-audit.csv" in export.headers["content-disposition"]
    assert f"'{formula_id}" in export.text

    created = await client.post(
        "/api/v1/workspace/api-keys",
        headers=auth_headers,
        json={"name": f"Audit permission test {uuid4().hex[:8]}"},
    )
    assert created.status_code == 201, created.text
    key = created.json()
    try:
        denied = await client.get(
            "/api/v1/audit/events",
            headers={"Authorization": f"Bearer {key['secret']}"},
        )
        assert denied.status_code == 403, denied.text
        assert "permission" in denied.json()["error"]["message"].lower()
    finally:
        revoked = await client.delete(
            f"/api/v1/workspace/api-keys/{key['id']}",
            headers=auth_headers,
        )
        assert revoked.status_code == 204, revoked.text
