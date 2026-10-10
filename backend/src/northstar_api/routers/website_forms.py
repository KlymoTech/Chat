"""First-party, revision-pinned website forms backed by the existing Lead pipeline.

POST is a real transaction: idempotency reservation, protected submission,
Lead/LeadProfile/LeadConsent, audit and durable outbox commit together.
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from html import escape
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from northstar_api.agent_purpose import AgentPurpose, get_agent_purpose
from northstar_api.dependencies import DBSession, require_roles
from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.lead_crm.domain import LeadLifecycleStatus
from northstar_api.lead_crm.models import LeadConsent
from northstar_api.lead_crm.website_marketing_suppression import has_workspace_marketing_suppression
from northstar_api.lead_crm.services import lead_domain_service
from northstar_api.models import Agent, AgentStatus, Lead, Role, Workspace, WorkspaceStatus
from northstar_api.routers.website_consent import _same_origin
from northstar_api.routers.website_cms import _lock_public_route_namespace
from northstar_api.security import Principal
from northstar_api.services.outbox import enqueue_event
from northstar_api.services.rate_limit import redis_services
from northstar_api.services.website_automation_runtime import enrol_website_lead
from northstar_api.services.website_builder_document import BuilderPageDocument
from northstar_api.services.website_form_client import SITE_FORM_CLIENT_JS
from northstar_api.website_cms_models import WebsitePage, WebsiteRevision
from northstar_api.services.website_form_contracts import (
    FormCreate, FormUpdate, FormVersionGuard, SiteFormDocument, validate_answers,
)
from northstar_api.website_form_models import WebsiteForm, WebsiteFormRevision, WebsiteFormSubmission

router = APIRouter(prefix="/site-forms", tags=["site-forms"])
Owner = Annotated[Principal, Depends(require_roles(Role.OWNER, Role.ADMIN))]

_FORM_STYLE = (
    "*{box-sizing:border-box}body{font:16px/1.6 system-ui,sans-serif;background:#f8fafc;color:#0f172a;"
    "margin:0;padding:24px}main{max-width:670px;margin:auto;background:white;padding:clamp(18px,5vw,42px);"
    "border-radius:14px;border:1px solid #cbd5e1}form{display:grid;gap:16px}label,legend{font-weight:650;"
    "display:block;margin-bottom:5px}input:not([type=checkbox],[type=radio]),select,textarea{width:100%;"
    "padding:11px;border:1px solid #64748b;border-radius:6px;font:inherit}fieldset{border:1px solid #cbd5e1;"
    "border-radius:8px;padding:12px}button{background:#1d4ed8;color:#fff;border:0;border-radius:7px;"
    "padding:13px 20px;font:inherit;cursor:pointer}.error{color:#991b1b}.required{color:#991b1b}"
    "[hidden]{display:none!important}.site-form-step{margin:12px 0;padding:16px;border:1px solid #cbd5e1;border-radius:9px}"
    ".site-form-step legend{font-size:1.08rem;font-weight:700;padding:0 6px}.site-form-nav{display:flex;gap:12px;margin:16px 0}"
    ".site-form-nav button{background:#475569}.site-form-progress{color:#475569;font-weight:600}"
    ".site-form-condition{border-left:3px solid #93c5fd;padding-left:12px;margin:12px 0}"
    ".honeypot{position:absolute;left:-10000px}a:focus,input:focus,button:focus,select:focus{"
    "outline:3px solid #f59e0b;outline-offset:2px}small{display:block;color:#475569}"
)
_STYLE_HASH = base64.b64encode(hashlib.sha256(_FORM_STYLE.encode()).digest()).decode()


def _html(content: str, *, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        content=("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
                 "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
                 "<title>Website enquiry</title><meta name=\"robots\" content=\"noindex\">"
                 f'<style>{_FORM_STYLE}</style><script defer src="/api/v1/site-forms/client.js"></script>'
                 f"</head><body><main>{content}</main></body></html>"),
        status_code=status_code,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'sha256-" + _STYLE_HASH +
                "'; script-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'self'"
            ),
        },
    )


def _field_html(field: Any) -> str:
    key = escape(field.key, quote=True)
    label = escape(field.label)
    # A conditional required field is enabled and validated by progressive
    # enhancement, and always enforced on the server for matching conditions.
    required = " required" if field.required and field.condition is None else ""
    required_hint = ' data-site-required="true"' if field.required else ""
    star = ' <span class="required">(required)</span>' if field.required else ""
    purpose = "<small>" + escape(field.purpose) + "</small>"
    if field.kind in {"checkbox", "consent"}:
        markup = (
            f'<div><label><input type="checkbox" name="{key}" value="on"{required_hint}{required}>'
            f' {label}{star}</label>{purpose}</div>'
        )
    elif field.kind == "radio":
        choices = "".join(
            '<label><input type="radio" name="' + key + '" value="' +
            escape(choice, quote=True) + '"' + required_hint + required +
            "> " + escape(choice) + "</label>"
            for choice in field.choices
        )
        markup = f"<fieldset><legend>{label}{star}</legend>{choices}{purpose}</fieldset>"
    elif field.kind == "select":
        options = '<option value="">Choose an option</option>' + "".join(
            '<option value="' + escape(choice, quote=True) + '">' + escape(choice) + "</option>"
            for choice in field.choices
        )
        markup = (
            f'<div><label for="{key}">{label}{star}</label>'
            f'<select id="{key}" name="{key}"{required_hint}{required}>{options}</select>{purpose}</div>'
        )
    elif field.kind == "text" and field.max_length > 240:
        markup = (
            f'<div><label for="{key}">{label}{star}</label>'
            f'<textarea id="{key}" name="{key}" maxlength="{field.max_length}"'
            f' rows="5"{required_hint}{required}></textarea>{purpose}</div>'
        )
    else:
        input_kind = "tel" if field.kind == "phone" else (
            field.kind if field.kind in {"email", "date"} else "text"
        )
        markup = (
            f'<div><label for="{key}">{label}{star}</label>'
            f'<input id="{key}" name="{key}" type="{input_kind}" maxlength="{field.max_length}"'
            f'{required_hint}{required}>{purpose}</div>'
        )
    if field.condition is None:
        return markup
    controller = escape(field.condition.field_key, quote=True)
    equals = escape(field.condition.equals, quote=True)
    instruction = (
        "<small>Only answer when " + escape(field.condition.field_key) +
        " equals " + escape(field.condition.equals) + ".</small>"
    )
    return (
        f'<div class="site-form-condition" data-condition-key="{controller}" '
        f'data-condition-equals="{equals}">{markup}{instruction}</div>'
    )


def _render_form(
    doc: SiteFormDocument, form: WebsiteForm, *, key: str,
    errors: dict[str, str] | None = None,
) -> HTMLResponse:
    issues = errors or {}
    error_markup = ""
    if issues:
        error_markup = (
            '<div role="alert" class="error"><h2>Please correct your submission</h2><ul>'
            + "".join("<li>" + escape(name + ": " + message) + "</li>" for name, message in issues.items())
            + "</ul></div>"
        )
    step_sections = []
    for step_index, heading in enumerate(doc.steps, start=1):
        content_fields = "".join(
            _field_html(field) for field in doc.fields if field.step == step_index
        )
        step_sections.append(
            f'<fieldset class="site-form-step" data-site-step="{step_index}">'
            f'<legend>{escape(heading)}</legend>{content_fields}</fieldset>'
        )
    content = (
        f"<h1>{escape(doc.title)}</h1><p>{escape(doc.description)}</p>{error_markup}"
        f'<form data-site-form action="/api/v1/site-forms/public/{form.workspace_id}/{escape(form.slug, quote=True)}"'
        f' method="post" accept-charset="utf-8">'
        '<label class="honeypot" aria-hidden="true">Leave blank'
        '<input name="_website" tabindex="-1" autocomplete="off"></label>'
        f'<input type="hidden" name="_version" value="{form.published_version}">'
        f'<input type="hidden" name="_submission_key" value="{escape(key, quote=True)}">'
        '<p class="site-form-progress" data-site-progress role="status" aria-live="polite"></p>'
        + "".join(step_sections)
        + '<div class="site-form-nav">'
        '<button type="button" data-site-back hidden>Previous step</button>'
        '<button type="button" data-site-next hidden>Next step</button>'
        '</div>'
        + "<p>" + escape(doc.privacy_notice) + "</p>"
        + '<button type="submit" data-site-submit>' + escape(doc.submit_label) + "</button></form>"
    )
    return _html(content, status_code=422 if issues else 200)


def _info(form: WebsiteForm, document: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(form.id), "slug": form.slug, "agentId": str(form.agent_id),
        "draftVersion": form.draft_version, "publishedVersion": form.published_version,
        "document": document,
    }


async def _agent(session: DBSession, *, tenant_id: UUID, workspace_id: UUID, agent_id: UUID, active: bool) -> Agent:
    agent = await session.scalar(select(Agent).where(
        Agent.id == agent_id,
        Agent.tenant_id == tenant_id, Agent.workspace_id == workspace_id,
        Agent.deleted_at.is_(None),
    ))
    if agent is None or (active and agent.status != AgentStatus.ACTIVE):
        raise HTTPException(409, "A valid active lead-generation agent is required")
    purpose = await get_agent_purpose(
        session, tenant_id=tenant_id, workspace_id=workspace_id, agent_id=agent_id,
    )
    if purpose is not AgentPurpose.LEAD_GENERATION:
        raise HTTPException(409, "Forms must target a lead-generation agent")
    return agent


async def _owner_form(session: DBSession, principal: Principal, form_id: UUID) -> WebsiteForm:
    if principal.workspace_id is None:
        raise HTTPException(400, "Select a workspace")
    form = await session.scalar(select(WebsiteForm).where(
        WebsiteForm.id == form_id, WebsiteForm.tenant_id == principal.tenant_id,
        WebsiteForm.workspace_id == principal.workspace_id,
    ))
    if form is None:
        raise HTTPException(404, "Form not found")
    return form


async def _revision(session: DBSession, form: WebsiteForm, version: int) -> WebsiteFormRevision:
    revision = await session.scalar(select(WebsiteFormRevision).where(
        WebsiteFormRevision.form_id == form.id, WebsiteFormRevision.version == version,
    ))
    if revision is None:
        raise HTTPException(409, "Form revision unavailable")
    return revision


@router.get("/client.js", include_in_schema=False)
async def site_form_client() -> Response:
    return Response(
        content=SITE_FORM_CLIENT_JS,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=300", "X-Content-Type-Options": "nosniff"},
    )


@router.get("")
async def list_forms(principal: Owner, session: DBSession) -> list[dict[str, Any]]:
    if principal.workspace_id is None:
        raise HTTPException(400, "Select a workspace")
    forms = (await session.scalars(select(WebsiteForm).where(
        WebsiteForm.tenant_id == principal.tenant_id,
        WebsiteForm.workspace_id == principal.workspace_id,
    ).order_by(WebsiteForm.updated_at.desc()))).all()
    results = []
    for form in forms:
        current = await _revision(session, form, form.draft_version)
        results.append(_info(form, current.document_json))
    return results


@router.post("", status_code=201)
async def create_form(payload: FormCreate, principal: Owner, session: DBSession) -> dict[str, Any]:
    if principal.workspace_id is None:
        raise HTTPException(400, "Select a workspace")
    await _agent(
        session, tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        agent_id=payload.agent_id, active=False,
    )
    form = WebsiteForm(
        tenant_id=principal.tenant_id, workspace_id=principal.workspace_id,
        agent_id=payload.agent_id, slug=payload.slug,
        draft_version=1,
    )
    session.add(form)
    try:
        await session.flush()
        document = payload.document.model_dump(mode="json")
        session.add(WebsiteFormRevision(
            form_id=form.id, version=1, document_json=document,
            created_by=principal.user_id,
        ))
        record_audit_event(
            session, tenant_id=principal.tenant_id, workspace_id=principal.workspace_id,
            actor_user_id=principal.user_id, action="site.form.created",
            entity_type="website_form", entity_id=str(form.id),
            category="lead", after={"slug":form.slug, "version":1},
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "Form slug already in use") from None
    return _info(form, document)


@router.put("/{form_id}")
async def update_form(
    form_id: UUID, payload: FormUpdate, principal: Owner, session: DBSession,
) -> dict[str, Any]:
    form = await _owner_form(session, principal, form_id)
    if form.draft_version != payload.expected_version:
        raise HTTPException(409, "Form changed; reload before saving")
    changed = await session.execute(update(WebsiteForm).where(
        WebsiteForm.id == form.id, WebsiteForm.draft_version == payload.expected_version,
    ).values(draft_version=payload.expected_version + 1, updated_at=datetime.now(UTC)))
    if changed.rowcount != 1:
        await session.rollback()
        raise HTTPException(409, "Form modified concurrently")
    form.draft_version = payload.expected_version + 1
    document = payload.document.model_dump(mode="json")
    session.add(WebsiteFormRevision(
        form_id=form.id, version=form.draft_version,
        document_json=document, created_by=principal.user_id,
    ))
    record_audit_event(
        session, tenant_id=principal.tenant_id, workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id, action="site.form.updated",
        entity_type="website_form", entity_id=str(form.id), category="lead",
        after={"slug":form.slug, "version":form.draft_version},
    )
    await session.commit()
    return _info(form, document)


@router.post("/{form_id}/publish")
async def publish_form(
    form_id: UUID, payload: FormVersionGuard, principal: Owner, session: DBSession,
) -> dict[str, Any]:
    form = await _owner_form(session, principal, form_id)
    if form.draft_version != payload.expected_version:
        raise HTTPException(409, "Form changed; reload before publishing")
    await _agent(
        session, tenant_id=principal.tenant_id,
        workspace_id=form.workspace_id, agent_id=form.agent_id, active=True,
    )
    revision = await _revision(session, form, form.draft_version)
    doc = SiteFormDocument.model_validate(revision.document_json)
    if form.published_version == form.draft_version:
        return _info(form, revision.document_json)
    changed = await session.execute(update(WebsiteForm).where(
        WebsiteForm.id == form.id,
        WebsiteForm.draft_version == payload.expected_version,
        WebsiteForm.published_version.is_distinct_from(payload.expected_version),
    ).values(published_version=form.draft_version, updated_at=datetime.now(UTC)))
    if changed.rowcount != 1:
        await session.rollback()
        raise HTTPException(409, "Form publication changed concurrently")
    form.published_version = form.draft_version
    record_audit_event(
        session, tenant_id=principal.tenant_id, workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id, action="site.form.published",
        entity_type="website_form", entity_id=str(form.id), category="lead",
        after={"slug":form.slug, "version":form.draft_version},
    )
    event = enqueue_event(
        session, tenant_id=principal.tenant_id, aggregate_type="website_form",
        aggregate_id=form.id, event_type="website.form.published",
        payload={"workspaceId":str(form.workspace_id), "version":form.draft_version},
    )
    event.workspace_id = form.workspace_id
    await session.commit()
    return _info(form, doc.model_dump(mode="json"))


async def _published_pages_embedding_form(
    session: DBSession, form: WebsiteForm,
) -> list[str]:
    """Inspect immutable public page revisions, not editable drafts."""
    published = (await session.execute(
        select(WebsitePage.slug, WebsiteRevision.document_json)
        .join(
            WebsiteRevision,
            (WebsiteRevision.page_id == WebsitePage.id)
            & (WebsiteRevision.version == WebsitePage.published_version),
        )
        .where(
            WebsitePage.tenant_id == form.tenant_id,
            WebsitePage.workspace_id == form.workspace_id,
            WebsitePage.published_version.is_not(None),
        )
    )).all()
    exact_url = f"/api/v1/site-forms/public/{form.workspace_id}/{form.slug}"
    dependent_pages: list[str] = []
    for slug, content in published:
        page_document = BuilderPageDocument.model_validate(content)
        stack = list(page_document.nodes)
        while stack:
            node = stack.pop()
            stack.extend(node.children)
            if node.kind == "form" and node.url == exact_url:
                dependent_pages.append(slug)
                break
    return dependent_pages


@router.post("/{form_id}/unpublish")
async def unpublish_form(
    form_id: UUID, payload: FormVersionGuard, principal: Owner, session: DBSession,
) -> dict[str, Any]:
    form = await _owner_form(session, principal, form_id)
    if form.draft_version != payload.expected_version:
        raise HTTPException(409, "Form changed; reload before unpublishing")
    if form.published_version is not None:
        # Same lock as page publication: no page may be left publicly embedding
        # a disabled form. Owner must remove/archive those embeds first.
        await _lock_public_route_namespace(session, principal)
        dependent_pages = await _published_pages_embedding_form(session, form)
        if dependent_pages:
            raise HTTPException(
                409, "Remove this form from published pages before unpublishing: "
                + ", ".join(dependent_pages[:10]),
            )
        old_publication = form.published_version
        changed = await session.execute(update(WebsiteForm).where(
            WebsiteForm.id == form.id,
            WebsiteForm.draft_version == payload.expected_version,
            WebsiteForm.published_version == old_publication,
        ).values(published_version=None, updated_at=datetime.now(UTC)))
        if changed.rowcount != 1:
            await session.rollback()
            raise HTTPException(409, "Form publication changed concurrently")
        form.published_version = None
        record_audit_event(
            session, tenant_id=principal.tenant_id, workspace_id=principal.workspace_id,
            actor_user_id=principal.user_id, action="site.form.unpublished",
            entity_type="website_form", entity_id=str(form.id), category="lead",
        )
        event = enqueue_event(
            session, tenant_id=principal.tenant_id,
            aggregate_type="website_form", aggregate_id=form.id,
            event_type="website.form.unpublished",
            payload={"workspaceId":str(form.workspace_id)},
        )
        event.workspace_id = form.workspace_id
        await session.commit()
    revision = await _revision(session, form, form.draft_version)
    return _info(form, revision.document_json)


@router.get("/{form_id}/submissions")
async def form_submission_receipts(
    form_id: UUID, principal: Owner, session: DBSession,
) -> list[dict[str, str | None]]:
    form = await _owner_form(session, principal, form_id)
    rows = (await session.scalars(select(WebsiteFormSubmission).where(
        WebsiteFormSubmission.tenant_id == principal.tenant_id,
        WebsiteFormSubmission.workspace_id == principal.workspace_id,
        WebsiteFormSubmission.form_id == form.id,
    ).order_by(WebsiteFormSubmission.created_at.desc()).limit(100))).all()
    return [
        {"receiptId":str(item.id), "leadId":str(item.lead_id) if item.lead_id else None,
         "createdAt":item.created_at.isoformat(), "version":str(item.form_version)}
        for item in rows
    ]


async def _public_form(
    session: DBSession, workspace_id: UUID, slug: str,
    *, allow_unpublished: bool = False,
) -> tuple[WebsiteForm, SiteFormDocument, Workspace]:
    workspace = await session.scalar(select(Workspace).where(
        Workspace.id == workspace_id, Workspace.status == WorkspaceStatus.ACTIVE,
    ))
    if workspace is None:
        raise HTTPException(404, "Published form unavailable")
    form = await session.scalar(select(WebsiteForm).where(
        WebsiteForm.tenant_id == workspace.tenant_id, WebsiteForm.workspace_id == workspace_id,
        WebsiteForm.slug == slug,
        *((WebsiteForm.published_version.is_not(None),) if not allow_unpublished else ()),
    ))
    if form is None or (not allow_unpublished and form.published_version is None):
        raise HTTPException(404, "Published form unavailable")
    active_version = form.published_version or form.draft_version
    rev = await _revision(session, form, active_version)
    return form, SiteFormDocument.model_validate(rev.document_json), workspace


@router.get("/public/{workspace_id}/{slug}", response_class=HTMLResponse)
async def public_form_page(
    workspace_id: UUID, slug: str, session: DBSession,
) -> HTMLResponse:
    form, document, _ = await _public_form(session, workspace_id, slug)
    return _render_form(document, form, key=str(uuid4()))


def _receipt(submission: WebsiteFormSubmission) -> dict[str, str]:
    return {
        "status":"accepted",
        "receiptId":str(submission.id),
        "eventId":str(submission.conversion_event_id),
    }


@router.post("/public/{workspace_id}/{slug}", response_model=None)
async def submit_public_form(
    workspace_id: UUID, slug: str, request: Request, session: DBSession,
) -> Response:
    _same_origin(request)
    mime = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if mime != "application/x-www-form-urlencoded":
        raise HTTPException(415, "Use the published website form")
    if len(await request.body()) > 20000:
        raise HTTPException(413, "Form request is too large")
    # Lookup historical receipts even after an owner has safely unpublished
    # the form. New enrolments are still forbidden when no revision is live.
    form, document, workspace = await _public_form(
        session, workspace_id, slug, allow_unpublished=True,
    )
    raw = await request.form()
    if len(raw) > 35 or any(not isinstance(value, str) for _, value in raw.multi_items()):
        raise HTTPException(422, "Invalid form submission")
    if any(len(raw.getlist(name)) > 1 for name in raw.keys()):
        raise HTTPException(422, "Duplicate field values are not accepted")
    if raw.get("_website"):
        raise HTTPException(422, "Please retry or contact the organization")
    key = str(raw.get("_submission_key", ""))
    if len(key) > 80:
        raise HTTPException(422, "Invalid submission identifier")
    try:
        UUID(key)
    except ValueError:
        raise HTTPException(422, "Invalid submission identifier") from None
    try:
        version = int(str(raw.get("_version", "0")))
    except ValueError:
        raise HTTPException(422, "Form version is invalid") from None
    values = {str(name): str(value) for name, value in raw.items()
              if name not in {"_submission_key", "_version", "_website"}}
    if len(values) > 30:
        raise HTTPException(422, "Too many fields")
    digest = hashlib.sha256(json.dumps(
        {"version":version, "values":values}, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    accept_json = "application/json" in request.headers.get("accept", "")
    prior = await session.scalar(select(WebsiteFormSubmission).where(
        WebsiteFormSubmission.form_id == form.id,
        WebsiteFormSubmission.idempotency_key == key,
    ))
    if prior is not None:
        if prior.request_digest != digest:
            raise HTTPException(409, "Submission identifier reused with changed answers")
        return (JSONResponse(_receipt(prior), headers={"Cache-Control":"no-store"})
                if accept_json else _html(
                    "<h1>Already received</h1><p role=\"status\">Your enquiry was recorded. "
                    "Receipt: " + escape(str(prior.id)) + "</p>"))
    # The initial public GET is only a snapshot: protect new submissions from
    # a concurrent unpublish/revision switch by locking and reading the live
    # publication pointer again within the eventual lead transaction.
    answers, errors = validate_answers(document, values)
    if errors:
        if accept_json:
            return JSONResponse(
                {"error":"validation_failed", "fieldErrors":errors},
                status_code=422, headers={"Cache-Control":"no-store"},
            )
        return _render_form(document, form, key=key, errors=errors)
    rate = await redis_services.check_rate_limit(
        f"site-form:{workspace_id}:{request.client.host if request.client else 'unknown'}",
        25, window_seconds=3600, scope="site_forms",
    )
    if not rate.allowed:
        raise HTTPException(429, "Please try later", headers={"Retry-After":str(rate.retry_after)})
    current_publication = await session.scalar(
        select(WebsiteForm.published_version).where(
            WebsiteForm.id == form.id,
            WebsiteForm.tenant_id == workspace.tenant_id,
            WebsiteForm.workspace_id == workspace_id,
        ).with_for_update()
    )
    if current_publication is None:
        raise HTTPException(410, "This form is closed and cannot accept new submissions")
    if current_publication != version:
        raise HTTPException(409, "This form changed; reload it before submitting")
    await _agent(
        session, tenant_id=workspace.tenant_id,
        workspace_id=workspace_id, agent_id=form.agent_id, active=True,
    )
    submission = WebsiteFormSubmission(
        tenant_id=workspace.tenant_id, workspace_id=workspace_id,
        form_id=form.id, form_version=version, idempotency_key=key,
        request_digest=digest, values_json=answers,
    )
    # Reserve uniqueness before creating a Lead. The savepoint makes concurrent
    # duplicate requests recoverable without losing another in-flight transaction.
    try:
        async with session.begin_nested():
            session.add(submission)
            await session.flush()
    except IntegrityError:
        prior = await session.scalar(select(WebsiteFormSubmission).where(
            WebsiteFormSubmission.form_id == form.id,
            WebsiteFormSubmission.idempotency_key == key,
        ))
        if prior is not None and prior.request_digest == digest:
            return (JSONResponse(_receipt(prior), headers={"Cache-Control":"no-store"})
                    if accept_json else _html(
                        "<h1>Already received</h1><p role=\"status\">Your enquiry was recorded. "
                        "Receipt: " + escape(str(prior.id)) + "</p>"))
        raise HTTPException(409, "Submission identifier conflict") from None

    def first(kind: str) -> str | None:
        for field in document.fields:
            if field.kind == kind:
                value = answers.get(field.key)
                if isinstance(value, str) and value:
                    return value
        return None

    name = next(
        (str(answers[field.key]) for field in document.fields
         if field.kind == "text" and field.key in {"name", "full_name"} and answers.get(field.key)),
        None,
    )
    lead = Lead(
        tenant_id=workspace.tenant_id, workspace_id=workspace_id,
        agent_id=form.agent_id, name=name,
        email=first("email"), phone=first("phone"),
        status=LeadLifecycleStatus.NEW.value, consent=True,
        fields_json={
            "sourceChannel":"website_form", "siteFormSlug":form.slug,
            "siteFormVersion":version, "siteFormSubmissionId":str(submission.id),
        },
    )
    session.add(lead)
    await session.flush()
    await lead_domain_service.ensure_profile(
        session, lead=lead, source_channel="website_form",
        source_provider="first_party",
    )
    consent_field = next(field for field in document.fields if field.kind == "consent")
    session.add(LeadConsent(
        tenant_id=workspace.tenant_id, lead_id=lead.id,
        consent_type="processing", status="granted", source="website_form",
        channel="web", text_version=f"{form.id}:{version}",
        captured_at=datetime.now(UTC),
        metadata_json={
            "formId":str(form.id), "formVersion":version,
            "fieldKey":consent_field.key, "purpose":consent_field.purpose,
        },
    ))
    if answers.get("marketing_opt_in") is True:
        # A checked optional box is the only possible source of an email
        # marketing grant here. Required enquiry-processing consent never
        # grants marketing permission. Preserve suppression across duplicate
        # Lead records with the same workspace and normalized email.
        earlier_suppression = await has_workspace_marketing_suppression(
            session,
            tenant_id=workspace.tenant_id,
            workspace_id=workspace_id,
            email=lead.email,
            exclude_lead_id=lead.id,
        )
        marketing_status = "pending_verification" if earlier_suppression else "granted"
        marketing_field = next(
            field for field in document.fields if field.key == "marketing_opt_in"
        )
        session.add(LeadConsent(
            tenant_id=workspace.tenant_id, lead_id=lead.id,
            consent_type="marketing", status=marketing_status,
            source="website_form", channel="email",
            text_version=f"{form.id}:{version}",
            captured_at=datetime.now(UTC),
            metadata_json={
                "formId": str(form.id), "formVersion": version,
                "fieldKey": marketing_field.key,
                "purpose": marketing_field.purpose,
                "requiresReview": marketing_status != "granted",
            },
        ))
        record_audit_event(
            session,
            tenant_id=workspace.tenant_id, workspace_id=workspace_id,
            actor_user_id=None,
            action="website.marketing.opt_in_captured",
            entity_type="lead", entity_id=str(lead.id), category="lead",
            after={
                "marketingConsent": marketing_status,
                "formId": str(form.id), "formVersion": version,
            },
            metadata={"method": "explicit_optional_checkbox"},
        )
        marketing_event = enqueue_event(
            session, tenant_id=workspace.tenant_id,
            aggregate_type="lead", aggregate_id=lead.id,
            event_type="lead.marketing.opt_in_recorded.v1",
            payload={
                "leadId": str(lead.id),
                "workspaceId": str(workspace_id),
                "marketingStatus": marketing_status,
                "formId": str(form.id),
                "formVersion": version,
            },
        )
        marketing_event.workspace_id = workspace_id
    event_payload = {
        "leadId":str(lead.id), "workspaceId":str(workspace_id),
        "agentId":str(form.agent_id), "formId":str(form.id),
        "formVersion":version, "submissionId":str(submission.id),
        "sourceChannel":"website_form", "reason":"lead_created",
    }
    for event_type in ("lead.captured.v1", "lead.created.v1", "lead.crm.sync.requested.v1"):
        event = enqueue_event(
            session, tenant_id=workspace.tenant_id,
            aggregate_type="lead", aggregate_id=lead.id,
            event_type=event_type, payload=event_payload,
        )
        event.workspace_id = workspace_id
    conversion = enqueue_event(
        session, tenant_id=workspace.tenant_id,
        aggregate_type="website_form", aggregate_id=submission.id,
        event_type="website.form.submitted.v1",
        payload=event_payload,
    )
    conversion.workspace_id = workspace_id
    # The same commit reserves any explicitly published internal workflow run.
    # No automation can contact a customer; CRM outbox dispatch is unchanged.
    await enrol_website_lead(
        session,
        tenant_id=workspace.tenant_id, workspace_id=workspace_id,
        lead_id=lead.id, source_category="form",
        event_key="website-form:" + str(submission.id),
    )
    await session.flush()
    submission.lead_id = lead.id
    submission.conversion_event_id = conversion.id
    record_audit_event(
        session,
        tenant_id=workspace.tenant_id,
        workspace_id=workspace_id,
        actor_user_id=None,
        action="site.form.submission.accepted",
        entity_type="website_form_submission",
        entity_id=str(submission.id),
        category="lead",
        after={
            "formId": str(form.id),
            "formVersion": version,
            "receiptId": str(submission.id),
            "conversionEventId": str(conversion.id),
        },
        metadata={"source": "first_party_form"},
    )
    await session.commit()
    if accept_json:
        return JSONResponse(_receipt(submission), status_code=201, headers={"Cache-Control":"no-store"})
    return _html(
        "<h1>Thank you</h1><p role=\"status\">Your enquiry was received.</p>"
        "<p>Receipt: " + escape(str(submission.id)) + "</p>"
    )
