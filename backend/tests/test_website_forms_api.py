"""First-party form-to-Lead flow, with replay-safe receipts and isolated revisions."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.audit_models import IntegrationAuditEvent
from northstar_api.lead_crm.models import LeadConsent, LeadProfile
from northstar_api.models import Lead, OutboxEvent
from northstar_api.website_form_models import WebsiteFormRevision, WebsiteFormSubmission

pytestmark = pytest.mark.usefixtures("crm_test_plan")


def _document(title: str = "Contact our team") -> dict:
    return {
        "title": title,
        "submit_label": "Send enquiry",
        "description": "We respond during office hours.",
        "privacy_notice": "Your contact details are used only to respond to this enquiry.",
        "fields": [
            {"key":"name", "label":"Full name", "kind":"text", "required":True,
             "purpose":"Identify the person", "max_length":160},
            {"key":"email", "label":"Email", "kind":"email", "required":True,
             "purpose":"Reply to the enquiry", "max_length":320},
            {"key":"message", "label":"Message", "kind":"text", "required":True,
             "purpose":"Understand your request", "max_length":1000},
            {"key":"processing_consent", "label":"I consent to enquiry processing",
             "kind":"consent", "required":True, "purpose":"Respond to my enquiry"},
        ],
    }


async def _create_form(
    client: AsyncClient, headers: dict[str, str],
) -> tuple[str, str, str]:
    workspace = await client.get("/api/v1/workspace", headers=headers)
    assert workspace.status_code == 200, workspace.text
    scope = workspace.json()["id"]
    agent = await client.post("/api/v1/agents", headers=headers, json={
        "name":"Site form " + uuid4().hex[:8],
        "description":"Public contact form delivery",
        "purpose":"lead_generation", "deploymentChannel":"website",
    })
    assert agent.status_code == 201, agent.text
    form_slug = "contact-" + uuid4().hex[:10]
    created = await client.post("/api/v1/site-forms", headers=headers, json={
        "slug":form_slug, "agent_id":agent.json()["id"], "document":_document(),
    })
    assert created.status_code == 201, created.text
    return created.json()["id"], scope, form_slug


def _values(key: str, version: int = 1) -> dict[str, str]:
    return {
        "_submission_key":key, "_version":str(version),
        "name":"山田 花子", "email":"hanako@example.com",
        "message":"Please contact me.", "processing_consent":"on",
    }


async def test_published_form_writes_exactly_one_existing_lead_with_consents_and_outbox(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    form_id, scope, slug = await _create_form(client, auth_headers)
    public = f"/api/v1/site-forms/public/{scope}/{slug}"
    assert (await client.get(public)).status_code == 404

    publication = await client.post(
        f"/api/v1/site-forms/{form_id}/publish",
        headers=auth_headers, json={"expected_version":1},
    )
    assert publication.status_code == 200, publication.text
    rendered = await client.get(public)
    assert rendered.status_code == 200, rendered.text
    assert '<form action=' in rendered.text
    assert 'name="processing_consent"' in rendered.text
    assert 'maxlength="1000"' in rendered.text
    assert 'name="_submission_key"' in rendered.text
    assert 'content-security-policy' in rendered.headers

    key = str(uuid4())
    data = _values(key)
    bad = await client.post(public, data={**data, "processing_consent":""},
                            headers={"Accept":"application/json"})
    assert bad.status_code == 422, bad.text
    assert "processing_consent" in bad.json()["fieldErrors"]

    sent = await client.post(public, data=data, headers={"Accept":"application/json"})
    assert sent.status_code == 201, sent.text
    receipt = sent.json()
    assert receipt["status"] == "accepted"
    assert UUID(receipt["receiptId"])
    assert UUID(receipt["eventId"])
    assert "email" not in sent.text
    assert "hanako" not in sent.text.lower()

    repeat = await client.post(public, data=data, headers={"Accept":"application/json"})
    assert repeat.status_code == 200, repeat.text
    assert repeat.json() == receipt
    changed = await client.post(
        public, data={**data, "message":"Different enquiry"},
        headers={"Accept":"application/json"},
    )
    assert changed.status_code == 409

    async with SessionFactory() as session:
        submission = await session.scalar(select(WebsiteFormSubmission).where(
            WebsiteFormSubmission.id == UUID(receipt["receiptId"]),
        ))
        assert submission is not None and submission.lead_id is not None
        assert submission.form_version == 1
        assert submission.values_json["name"] == "山田 花子"
        lead = await session.get(Lead, submission.lead_id)
        assert lead is not None
        assert lead.workspace_id == UUID(scope)
        assert lead.email == "hanako@example.com"
        assert lead.name == "山田 花子"
        assert lead.status == "new"
        assert lead.consent is True
        profile = await session.scalar(select(LeadProfile).where(LeadProfile.lead_id == lead.id))
        assert profile is not None and profile.source_channel == "website_form"
        consent = await session.scalar(select(LeadConsent).where(LeadConsent.lead_id == lead.id))
        assert consent is not None and consent.status == "granted"
        assert consent.text_version == f"{form_id}:1"
        conversions = await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.aggregate_type == "website_form",
            OutboxEvent.aggregate_id == str(submission.id),
            OutboxEvent.event_type == "website.form.submitted.v1",
        ))
        lead_events = (await session.scalars(select(OutboxEvent).where(
            OutboxEvent.aggregate_type == "lead",
            OutboxEvent.aggregate_id == str(lead.id),
        ))).all()
        audit = await session.scalar(select(IntegrationAuditEvent).where(
            IntegrationAuditEvent.entity_type == "website_form_submission",
            IntegrationAuditEvent.entity_id == str(submission.id),
            IntegrationAuditEvent.action == "site.form.submission.accepted",
        ))
        assert audit is not None
        assert audit.after_json["receiptId"] == str(submission.id)
        assert audit.actor_user_id is None
        assert "hanako@example.com" not in str(audit.after_json)

    assert conversions == 1
    assert {"lead.created.v1", "lead.captured.v1", "lead.crm.sync.requested.v1"} <= {
        event.event_type for event in lead_events
    }

    owner_receipts = await client.get(
        f"/api/v1/site-forms/{form_id}/submissions", headers=auth_headers,
    )
    assert owner_receipts.status_code == 200
    assert owner_receipts.json()[0]["receiptId"] == receipt["receiptId"]
    assert "hanako@example.com" not in owner_receipts.text

    closed = await client.post(
        f"/api/v1/site-forms/{form_id}/unpublish", headers=auth_headers,
        json={"expected_version":1},
    )
    assert closed.status_code == 200
    same_after_close = await client.post(
        public, data=data, headers={"Accept":"application/json"},
    )
    assert same_after_close.status_code == 200
    assert same_after_close.json() == receipt
    new_after_close = await client.post(
        public, data=_values(str(uuid4())), headers={"Accept":"application/json"},
    )
    assert new_after_close.status_code == 410


async def test_draft_edits_never_mutate_published_form_and_publishing_requires_fresh_version(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    form_id, scope, slug = await _create_form(client, auth_headers)
    public = f"/api/v1/site-forms/public/{scope}/{slug}"
    assert (await client.post(
        f"/api/v1/site-forms/{form_id}/publish", headers=auth_headers,
        json={"expected_version":1},
    )).status_code == 200

    modified = _document("Updated contact page")
    saved = await client.put(
        f"/api/v1/site-forms/{form_id}", headers=auth_headers,
        json={"expected_version":1, "document":modified},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["draftVersion"] == 2
    assert saved.json()["publishedVersion"] == 1
    assert (await client.put(
        f"/api/v1/site-forms/{form_id}", headers=auth_headers,
        json={"expected_version":1, "document":modified},
    )).status_code == 409
    assert "Contact our team" in (await client.get(public)).text
    assert "Updated contact page" not in (await client.get(public)).text

    promoted = await client.post(
        f"/api/v1/site-forms/{form_id}/publish", headers=auth_headers,
        json={"expected_version":2},
    )
    assert promoted.status_code == 200, promoted.text
    assert "Updated contact page" in (await client.get(public)).text

    old_version = await client.post(
        public, data=_values(str(uuid4()), 1), headers={"Accept":"application/json"},
    )
    assert old_version.status_code == 409
    unpub = await client.post(
        f"/api/v1/site-forms/{form_id}/unpublish", headers=auth_headers,
        json={"expected_version":2},
    )
    assert unpub.status_code == 200
    assert (await client.get(public)).status_code == 404

    async with SessionFactory() as session:
        revisions = await session.scalar(select(func.count()).select_from(WebsiteFormRevision).where(
            WebsiteFormRevision.form_id == UUID(form_id),
        ))
    assert revisions == 2


async def test_public_form_rejects_unsafe_fields_and_owner_endpoints_require_auth(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    form_id, scope, slug = await _create_form(client, auth_headers)
    assert (await client.get("/api/v1/site-forms")).status_code == 401
    assert (await client.post(
        f"/api/v1/site-forms/{form_id}/publish",
        json={"expected_version":1},
    )).status_code == 401
    assert (await client.post(
        f"/api/v1/site-forms/{form_id}/publish",
        headers=auth_headers, json={"expected_version":1},
    )).status_code == 200
    public = f"/api/v1/site-forms/public/{scope}/{slug}"
    assert (await client.post(
        public, data={**_values(str(uuid4())), "unexpected":"sneaky"},
        headers={"Accept":"application/json"},
    )).status_code == 422
    assert (await client.post(
        public, data={**_values(str(uuid4())), "_website":"bot"},
        headers={"Accept":"application/json"},
    )).status_code == 422
    assert (await client.post(
        public, data=_values(str(uuid4())),
        headers={"Origin":"https://different.example", "Accept":"application/json"},
    )).status_code == 403



async def test_site_page_form_blocks_require_published_same_workspace_form(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    form_id, workspace_id, slug = await _create_form(client, auth_headers)
    site_slug = "site-contact-" + uuid4().hex[:8]
    form_url = f"/api/v1/site-forms/public/{workspace_id}/{slug}"
    document = {
        "schema_version":1, "slug":site_slug, "title":"Enquiry",
        "nodes":[{"id":"section","kind":"section","children":[
            {"id":"enquiry","kind":"form","text":"Talk to our team","url":form_url},
        ]}],
    }
    created = await client.post(
        "/api/v1/site-cms/pages", headers=auth_headers, json=document,
    )
    assert created.status_code == 201, created.text
    page_id = created.json()["id"]
    for action in ("submit", "approve"):
        transitioned = await client.post(
            f"/api/v1/site-cms/pages/{page_id}/{action}", headers=auth_headers,
        )
        assert transitioned.status_code == 200, transitioned.text

    cannot_publish = await client.post(
        f"/api/v1/site-cms/pages/{page_id}/publish", headers=auth_headers,
    )
    assert cannot_publish.status_code == 409, cannot_publish.text

    form_published = await client.post(
        f"/api/v1/site-forms/{form_id}/publish",
        headers=auth_headers, json={"expected_version":1},
    )
    assert form_published.status_code == 200, form_published.text
    page_published = await client.post(
        f"/api/v1/site-cms/pages/{page_id}/publish", headers=auth_headers,
    )
    assert page_published.status_code == 200, page_published.text
    public_page = await client.get(
        f"/api/v1/site-cms/public/{workspace_id}/{site_slug}",
    )
    assert public_page.status_code == 200, public_page.text
    assert form_url in public_page.text
    assert 'sandbox="allow-forms allow-same-origin"' in public_page.text
    assert "frame-src 'self'" in public_page.headers["content-security-policy"]

    # An owned page may not embed a different workspace's public form.
    foreign_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    wrong = dict(document)
    wrong["slug"] = "foreign-" + uuid4().hex[:8]
    wrong["nodes"] = [{"id":"section","kind":"section","children":[
        {"id":"foreign","kind":"form","text":"Wrong workspace",
         "url":f"/api/v1/site-forms/public/{foreign_id}/{slug}"},
    ]}]
    foreign_page = await client.post(
        "/api/v1/site-cms/pages", headers=auth_headers, json=wrong,
    )
    assert foreign_page.status_code == 201, foreign_page.text
    foreign_page_id = foreign_page.json()["id"]
    for action in ("submit", "approve"):
        transitioned = await client.post(
            f"/api/v1/site-cms/pages/{foreign_page_id}/{action}", headers=auth_headers,
        )
        assert transitioned.status_code == 200, transitioned.text
    assert (await client.post(
        f"/api/v1/site-cms/pages/{foreign_page_id}/publish",
        headers=auth_headers,
    )).status_code == 409
