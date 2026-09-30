from types import SimpleNamespace
from uuid import UUID

from northstar_api.workers.zoho_flow_lead_delivery import build_flow_payload, retry_delay


def test_flow_payload_includes_saved_phone_once_and_current_source() -> None:
    lead = SimpleNamespace(
        id=UUID("fca62030-92af-4cc2-8d64-212842d86e69"),
        workspace_id=UUID("77f34f39-2637-4ec4-95e6-ebe3f50fbe57"),
        name="Manoj Sharma",
        email="manoj@example.com",
        phone="9898989898",
        status="new",
        fields_json={"sourceChannel": "widget"},
    )
    profile = SimpleNamespace(
        first_name="Manoj", last_name="Sharma", source_channel="widget", source_provider="widget"
    )

    payload = build_flow_payload(lead, profile, UUID("d43a99b8-3c57-4201-b6a9-aea2f40b4db9"))

    assert payload["lead_id"] == str(lead.id)
    assert payload["workspace_id"] == str(lead.workspace_id)
    assert payload["first_name"] == "Manoj"
    assert payload["last_name"] == "Sharma"
    assert payload["phone"] == "9898989898"
    assert payload["source"] == "widget"
    assert "phone_number" not in payload


def test_anonymous_flow_payload_has_readable_name_and_empty_contact_values() -> None:
    lead = SimpleNamespace(
        id=UUID("7cbf06a2-e30c-4a13-b948-17b7463c9967"),
        workspace_id=UUID("77f34f39-2637-4ec4-95e6-ebe3f50fbe57"),
        name=None,
        email=None,
        phone=None,
        status="new",
        fields_json={},
    )

    payload = build_flow_payload(lead, None, UUID("d43a99b8-3c57-4201-b6a9-aea2f40b4db9"))

    assert payload["first_name"] == "Anonymous"
    assert payload["last_name"] == "Visitor"
    assert payload["workspace_id"] == str(lead.workspace_id)
    assert payload["email"] is None
    assert payload["phone"] is None


def test_flow_retry_delay_uses_bounded_exponential_backoff() -> None:
    assert [retry_delay(attempt) for attempt in (1, 2, 3, 7, 20)] == [1, 2, 4, 60, 60]
