"""Database/API acceptance tests. Use the repository's real app and fixtures.

Model calls are deterministic test doubles; these tests do not certify NVIDIA,
object storage, WhatsApp delivery, or PostgreSQL concurrency in production.
"""

import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_education_runtime_authorization import (
    _create_agent,
    _create_batch,
    _create_course,
    _create_enrollment,
    _create_identity,
    _create_student,
    _workspace_headers,
)

from northstar_api.config import get_settings
from northstar_api.database import SessionFactory
from northstar_api.models import Agent, AgentStatus, IngestionJob, KnowledgeSource
from northstar_api.services.llm import nvidia_adapter

pytestmark = pytest.mark.usefixtures("crm_test_plan")


async def call(client, headers, method, path, body=None, expected=200):
    result = await client.request(
        method, "/api/v1" + path, headers=headers, **({"json": body} if body is not None else {})
    )
    assert result.status_code == expected, result.text
    return result.json()


@pytest.fixture
async def course_setup(client, auth_headers, monkeypatch):
    async def documents(texts):
        return [[1.0] + [0.0] * (get_settings().embedding_dimension - 1) for _ in texts]

    async def query(text):
        return (await documents([text]))[0]

    async def generated(**kwargs):
        return SimpleNamespace(content="Paper A approved lesson. [S1]")

    monkeypatch.setattr(nvidia_adapter, "embed_documents", documents)
    monkeypatch.setattr(nvidia_adapter, "embed_query", query)
    monkeypatch.setattr(nvidia_adapter, "generate_grounded", generated)
    _, headers = await _workspace_headers(client, auth_headers)
    suffix = uuid4().hex[:10]
    agent = await _create_agent(client, headers, name="Course release " + suffix)
    student = await _create_student(client, headers, "ST-" + suffix)
    phone = "+919" + str(int(suffix, 16) % 1000000000).zfill(9)
    await _create_identity(
        client, headers, student_id=student["id"], identity_type="whatsapp", identifier=phone
    )
    course = await _create_course(client, headers, "CMA-" + suffix)
    batch = await _create_batch(client, headers, course_id=course["id"], code="B-" + suffix)
    enrollment = await _create_enrollment(
        client,
        headers,
        student_id=student["id"],
        course_id=course["id"],
        batch_id=batch["id"],
        agent_id=agent["id"],
    )
    curriculum = await call(
        client,
        headers,
        "POST",
        "/education/knowledge/curricula",
        {"courseId": course["id"], "code": "2026", "name": "Reviewed 2026 curriculum"},
        201,
    )
    papers = []
    for code in ("P1", "P2"):
        papers.append(
            await call(
                client,
                headers,
                "POST",
                "/education/knowledge/papers",
                {"curriculumId": curriculum["id"], "code": code, "name": "Paper " + code},
                201,
            )
        )
    await call(
        client,
        headers,
        "PUT",
        "/education/knowledge/batch-curriculum",
        {"batchId": batch["id"], "curriculumId": curriculum["id"]},
    )
    prefix = f"/agents/{agent['id']}/education-knowledge"
    await call(
        client,
        headers,
        "PUT",
        prefix + f"/enrollments/{enrollment['id']}/access",
        {
            "curriculumId": curriculum["id"],
            "paperIds": [papers[0]["id"]],
            "selectedPaperId": papers[0]["id"],
            "expectedRevision": 0,
        },
    )
    async with SessionFactory() as session:
        entity = await session.get(Agent, UUID(agent["id"]))
        entity.status = AgentStatus.ACTIVE
        await session.commit()
    return dict(
        headers=headers,
        agent=agent,
        course=course,
        batch=batch,
        student=student,
        enrollment=enrollment,
        curriculum=curriculum,
        papers=papers,
        prefix=prefix,
        phone=phone,
    )


async def source_assignment(client, setup):
    h, p = setup["headers"], setup["prefix"]
    body = {
        "idempotencyKey": str(uuid4()),
        "title": "Mixed paper source",
        "kind": "text",
        "content": "Paper A approved lesson\n\nPaper B PRIVATE_SECRET",
        "destination": {
            "courseId": setup["course"]["id"],
            "curriculumId": setup["curriculum"]["id"],
            "mixedPapers": True,
        },
    }
    first = await call(client, h, "POST", p + "/uploads", body, 201)
    repeated = await call(client, h, "POST", p + "/uploads", body, 201)
    assert first["sourceId"] == repeated["sourceId"]
    version = await call(client, h, "POST", p + f"/sources/{first['sourceId']}/snapshot", expected=201)
    detail = await call(client, h, "GET", p + f"/versions/{version['id']}")
    body = {
        "idempotencyKey": str(uuid4()),
        "sourceVersionId": version["id"],
        "courseId": setup["course"]["id"],
        "curriculumId": setup["curriculum"]["id"],
        "paperId": setup["papers"][0]["id"],
        "blockIds": [detail["blocks"][0]["id"]],
    }
    assignment = await call(client, h, "POST", p + "/assignments", body, 201)
    return version, assignment, body


async def publish(client, setup, version, assignment):
    h, p = setup["headers"], setup["prefix"]
    await call(
        client,
        h,
        "POST",
        p + f"/assignments/{assignment['id']}/approve",
        {
            "expectedRevision": assignment["revision"],
            "expectedSourceHash": version["recordHash"],
            "reason": "Compared original content and confirmed Paper P1 audience",
        },
    )
    for _ in range(2):
        row = await call(
            client,
            h,
            "POST",
            p + f"/assignments/{assignment['id']}/prepare",
            {"expectedRevision": assignment["revision"]},
            202,
        )
        assert row["indexStatus"] == "ready"
    candidate = await call(
        client,
        h,
        "POST",
        p + "/releases",
        {
            "courseId": setup["course"]["id"],
            "curriculumId": setup["curriculum"]["id"],
            "assignmentIds": [assignment["id"]],
        },
        201,
    )
    head = await call(
        client,
        h,
        "POST",
        p + f"/releases/{candidate['id']}/publish",
        {"expectedEpoch": candidate["expectedEpoch"]},
    )
    retry = await call(
        client,
        h,
        "POST",
        p + f"/releases/{candidate['id']}/publish",
        {"expectedEpoch": candidate["expectedEpoch"]},
    )
    assert retry["epoch"] == head["epoch"]
    return candidate, head


async def test_teacher_approved_faq_requires_release_and_stays_course_scoped(client, course_setup):
    from northstar_api.services.course_knowledge import Boundary, match_published_faq, resolve_context

    s = course_setup
    h, p = s["headers"], s["prefix"]
    version, assignment, _ = await source_assignment(client, s)
    await publish(client, s, version, assignment)
    faq = await call(client, h, "POST", p + "/faqs", {
        "courseId": s["course"]["id"], "curriculumId": s["curriculum"]["id"],
        "paperId": s["papers"][0]["id"], "question": "What is the approved lesson?",
        "variants": ["Explain the approved lesson"], "answer": "The reviewed lesson answer.",
        "references": [{"kind": "course_assignment", "assignment_id": assignment["id"]}],
    }, 201)
    async with SessionFactory() as session:
        agent_row = await session.get(Agent, UUID(s["agent"]["id"]))
        assert agent_row is not None
        boundary = Boundary(agent_row.tenant_id, agent_row.workspace_id, agent_row.id)
        context = await resolve_context(session, boundary, UUID(s["enrollment"]["id"]))
        assert await match_published_faq(session, boundary, context, faq["question"], "English") is None
    approved = await call(client, h, "POST", p + f"/faqs/{faq['id']}/approve", {"expectedRevision": 1, "reason": "Teacher verified against the published lesson"})
    assert approved["status"] == "approved"
    current = await call(client, h, "GET", p + "/status")
    head = next(item for item in current["heads"] if item["courseId"] == s["course"]["id"])
    candidate = await call(client, h, "POST", p + "/releases", {
        "courseId": s["course"]["id"], "curriculumId": s["curriculum"]["id"],
        "assignmentIds": [assignment["id"]], "faqIds": [faq["id"]],
    }, 201)
    await call(client, h, "POST", p + f"/releases/{candidate['id']}/publish", {"expectedEpoch": head["epoch"]})
    async with SessionFactory() as session:
        context = await resolve_context(session, boundary, UUID(s["enrollment"]["id"]))
        matched = await match_published_faq(session, boundary, context, "Explain the approved lesson", "English")
        assert matched is not None and matched[0].answer == "The reviewed lesson answer."
        assert await match_published_faq(session, boundary, context, "Explain a different lesson", "English") is None
    await call(client, h, "POST", p + f"/faqs/{faq['id']}/withdraw", {"reason": "Teacher correction pending"})
    async with SessionFactory() as session:
        fresh = await resolve_context(session, boundary, UUID(s["enrollment"]["id"]))
        assert fresh.context_fingerprint != context.context_fingerprint
        assert await match_published_faq(session, boundary, fresh, faq["question"], "English") is None


async def test_bulk_enrollment_access_sync_snapshots_papers_and_preserves_manual_access(client, course_setup):
    """Bulk access is staff-triggered, snapshot-only, and never overwrites manual grants."""
    from northstar_api.course_knowledge_models import CourseEnrollmentAccess

    s = course_setup
    student = await _create_student(client, s["headers"], "SYNC-" + uuid4().hex[:8])
    enrollment = await _create_enrollment(
        client, s["headers"], student_id=student["id"], course_id=s["course"]["id"],
        batch_id=s["batch"]["id"], agent_id=s["agent"]["id"],
    )
    preview = await call(client, s["headers"], "POST", s["prefix"] + "/enrollment-access/sync-preview", {
        "courseId": s["course"]["id"], "batchId": s["batch"]["id"],
    })
    item = next(value for value in preview["items"] if value["enrollmentId"] == enrollment["id"])
    assert item["disposition"] == "will_create"
    assert set(item["proposedPaperIds"]) == {paper["id"] for paper in s["papers"]}
    applied = await call(client, s["headers"], "POST", s["prefix"] + "/enrollment-access/sync-apply", {
        "courseId": s["course"]["id"], "batchId": s["batch"]["id"], "enrollmentIds": [enrollment["id"]],
    })
    assert applied["created"] == 1 and applied["repaired"] == 0
    async with SessionFactory() as session:
        access = await session.get(CourseEnrollmentAccess, UUID(enrollment["id"]))
        assert access is not None and access.access_origin == "enrollment_sync"
        assert set(access.paper_ids) == {paper["id"] for paper in s["papers"]}
    later_paper = await call(client, s["headers"], "POST", "/education/knowledge/papers", {
        "curriculumId": s["curriculum"]["id"], "code": "P3", "name": "Paper P3",
    }, 201)
    later_preview = await call(client, s["headers"], "POST", s["prefix"] + "/enrollment-access/sync-preview", {
        "courseId": s["course"]["id"], "batchId": s["batch"]["id"],
    })
    later_item = next(value for value in later_preview["items"] if value["enrollmentId"] == enrollment["id"])
    assert later_item["disposition"] == "will_repair"
    assert later_paper["id"] in later_item["proposedPaperIds"]
    manual_item = next(value for value in later_preview["items"] if value["enrollmentId"] == s["enrollment"]["id"])
    assert manual_item["disposition"] == "manual_preserved"


async def test_hi_always_reopens_the_verified_course_menu(client, course_setup):
    from northstar_api.education_enrollments import EducationEnrollment
    from northstar_api.education_student_identities import EducationStudentIdentity
    from northstar_api.services.course_knowledge import Boundary
    from northstar_api.services.course_knowledge_selection import resolve_study_selection

    s = course_setup
    async with SessionFactory() as session:
        agent = await session.get(Agent, UUID(s["agent"]["id"]))
        identity = await session.scalar(select(EducationStudentIdentity).where(EducationStudentIdentity.student_id == UUID(s["student"]["id"])))
        enrollment = await session.get(EducationEnrollment, UUID(s["enrollment"]["id"]))
        assert agent and identity and enrollment
        boundary = Boundary(agent.tenant_id, agent.workspace_id, agent.id)
        first = await resolve_study_selection(session, boundary, identity.id, [enrollment], "Hi")
        assert first.prompt and "Choose your active course" in first.prompt
        selected = await resolve_study_selection(session, boundary, identity.id, [enrollment], "1")
        assert selected.enrollment is not None
        repeated = await resolve_study_selection(session, boundary, identity.id, [enrollment], "Hi")
        assert repeated.prompt and "Choose your active course" in repeated.prompt


async def test_two_enrollments_switch_and_revocation_updates_course_menu(client, course_setup):
    from northstar_api.education_enrollments import EducationEnrollment
    from northstar_api.education_student_identities import EducationStudentIdentity
    from northstar_api.services.course_knowledge import Boundary
    from northstar_api.services.course_knowledge_selection import resolve_study_selection

    s = course_setup
    other_course = await _create_course(client, s["headers"], "CPA-" + uuid4().hex[:8])
    other_batch = await _create_batch(client, s["headers"], course_id=other_course["id"], code="CPA-B")
    other = await _create_enrollment(client, s["headers"], student_id=s["student"]["id"],
        course_id=other_course["id"], batch_id=other_batch["id"], agent_id=s["agent"]["id"])
    curriculum = await call(client, s["headers"], "POST", "/education/knowledge/curricula",
        {"courseId": other_course["id"], "code": "2026", "name": "CPA 2026"}, 201)
    paper = await call(client, s["headers"], "POST", "/education/knowledge/papers",
        {"curriculumId": curriculum["id"], "code": "P1", "name": "CPA Paper"}, 201)
    await call(client, s["headers"], "PUT", "/education/knowledge/batch-curriculum",
        {"batchId": other_batch["id"], "curriculumId": curriculum["id"]})
    await call(client, s["headers"], "PUT", s["prefix"] + f"/enrollments/{other['id']}/access",
        {"curriculumId": curriculum["id"], "paperIds": [paper["id"]],
         "selectedPaperId": paper["id"], "expectedRevision": 0})
    async with SessionFactory() as session:
        agent = await session.get(Agent, UUID(s["agent"]["id"]))
        identity = await session.scalar(select(EducationStudentIdentity).where(
            EducationStudentIdentity.student_id == UUID(s["student"]["id"])))
        first = await session.get(EducationEnrollment, UUID(s["enrollment"]["id"]))
        second = await session.get(EducationEnrollment, UUID(other["id"]))
        boundary = Boundary(agent.tenant_id, agent.workspace_id, agent.id)
        menu = await resolve_study_selection(session, boundary, identity.id, [first, second], "Hi")
        assert menu.prompt and s["course"]["name"] in menu.prompt and other_course["name"] in menu.prompt
        await session.flush()
        chosen = await resolve_study_selection(session, boundary, identity.id, [first, second], "2")
        assert chosen.enrollment and chosen.enrollment.id == second.id
        await session.flush()
        reopened = await resolve_study_selection(session, boundary, identity.id, [first, second], "Hi")
        assert reopened.prompt and other_course["name"] in reopened.prompt
        await session.flush()
        revoked = await resolve_study_selection(session, boundary, identity.id, [first], "Hi")
        assert revoked.prompt and s["course"]["name"] in revoked.prompt
        assert other_course["name"] not in revoked.prompt


async def test_whatsapp_turn_audit_is_idempotent_and_downloadable(client, course_setup):
    import hashlib

    from northstar_api.course_knowledge_models import CourseAcademicReview, CourseWhatsappTurn
    from northstar_api.models import (
        Channel,
        Conversation,
        Message,
        MessageRole,
        WhatsAppConnection,
        WhatsAppInboundMessage,
    )
    from northstar_api.services.course_whatsapp_audit import sync_course_whatsapp_turn

    s = course_setup
    async with SessionFactory() as session:
        agent = await session.get(Agent, UUID(s["agent"]["id"]))
        assert agent is not None
        connection = WhatsAppConnection(tenant_id=agent.tenant_id, workspace_id=agent.workspace_id,
            agent_id=agent.id, waba_id="audit", phone_number_id="audit-phone",
            access_token_encrypted=b"test", status="connected")
        conversation = Conversation(tenant_id=agent.tenant_id, workspace_id=agent.workspace_id,
            agent_id=agent.id, channel=Channel.WHATSAPP, visitor_id=s["phone"].lstrip("+"))
        session.add_all([connection, conversation])
        await session.flush()
        receipt = WhatsAppInboundMessage(tenant_id=agent.tenant_id, workspace_id=agent.workspace_id,
            connection_id=connection.id, phone_number_id=connection.phone_number_id,
            provider_message_id="faq-audit-" + uuid4().hex, sender_wa_id=s["phone"].lstrip("+"),
            message_type="text", message_text="My number is 9876543210", status="processed",
            conversation_id=conversation.id, outbound_message_id="audit-out", outbound_message_ids=["audit-out"])
        session.add(receipt)
        await session.flush()
        key = "wa:" + hashlib.sha256(receipt.provider_message_id.encode()).hexdigest()
        session.add_all([
            Message(tenant_id=agent.tenant_id, workspace_id=agent.workspace_id, conversation_id=conversation.id,
                sequence=1, role=MessageRole.USER, content=receipt.message_text, idempotency_key=key),
            Message(tenant_id=agent.tenant_id, workspace_id=agent.workspace_id, conversation_id=conversation.id,
                sequence=2, role=MessageRole.ASSISTANT, content="Your number is 9876543210", finish_reason="stop"),
        ])
        await session.flush()
        answer_message = await session.scalar(select(Message).where(
            Message.conversation_id == conversation.id, Message.role == MessageRole.ASSISTANT))
        review = CourseAcademicReview(tenant_id=agent.tenant_id, workspace_id=agent.workspace_id,
            agent_id=agent.id, message_id=answer_message.id,
            enrollment_id=UUID(s["enrollment"]["id"]), question=receipt.message_text,
            reason="needs_teacher_review", status="open")
        session.add(review)
        await session.flush()
        review_id = review.id
        await sync_course_whatsapp_turn(session, agent=agent, receipt=receipt, answer_path="workflow")
        # A course choice can resume a pending question in the chat record;
        # the audit must still retain what arrived in this provider receipt.
        stored_question = await session.scalar(select(Message).where(Message.idempotency_key == key))
        stored_question.content = "Question resumed after course selection"
        await sync_course_whatsapp_turn(session, agent=agent, receipt=receipt, answer_path="workflow")
        receipt.status = "failed"
        receipt.last_error = "processing failed: RuntimeError"
        failed_turn = await sync_course_whatsapp_turn(session, agent=agent, receipt=receipt)
        assert failed_turn.delivery_status == "failed"
        receipt.status = "processed"
        receipt.last_error = None
        retried_turn = await sync_course_whatsapp_turn(session, agent=agent, receipt=receipt)
        assert retried_turn.delivery_status == "submitted"
        await session.commit()
        count = await session.scalar(select(func.count()).select_from(CourseWhatsappTurn).where(CourseWhatsappTurn.receipt_id == receipt.id))
        assert count == 1
        turn = await session.scalar(select(CourseWhatsappTurn).where(CourseWhatsappTurn.receipt_id == receipt.id))
        assert turn.question == "My number is 9876543210"
        assert turn.review_id == review_id and turn.review_status == "open"
    path = s["prefix"] + "/whatsapp-turns/export"
    exported = await client.get("/api/v1" + path + "?format=json", headers=s["headers"])
    assert exported.status_code == 200
    item = next(row for row in exported.json() if row["answerPath"] == "workflow")
    assert "9876543210" not in item["question"] and "9876543210" not in item["answer"]
    assert item["reviewStatus"] == "open"
    filtered = await client.get("/api/v1" + path + "?format=json&answer_path=workflow&review_status=open", headers=s["headers"])
    assert filtered.status_code == 200 and len(filtered.json()) == 1
    excluded = await client.get("/api/v1" + path + "?format=json&answer_path=faq", headers=s["headers"])
    assert excluded.status_code == 200 and excluded.json() == []
    csv_result = await client.get("/api/v1" + path + "?format=csv", headers=s["headers"])
    assert csv_result.status_code == 200 and "answerPath" in csv_result.text
    resolved = await client.post("/api/v1/education/academic-reviews/" + str(review_id) + "/resolve",
        headers=s["headers"], json={"outcome": "confirmed", "resolution": "Checked source"})
    assert resolved.status_code == 200, resolved.text
    updated = await client.get("/api/v1" + path + "?format=json&review_status=confirmed", headers=s["headers"])
    assert updated.status_code == 200 and len(updated.json()) == 1


async def test_release_lifecycle_scoped_preview_and_withdrawal(client, course_setup):
    s = course_setup
    h, p = s["headers"], s["prefix"]
    version, assignment, _ = await source_assignment(client, s)
    preview = {
        "enrollmentId": s["enrollment"]["id"],
        "query": "lesson",
        "selectedPaperId": s["papers"][0]["id"],
    }
    unpublished = await call(client, h, "POST", p + "/preview", preview)
    assert unpublished["evidence"] == []
    await publish(client, s, version, assignment)
    result = await call(client, h, "POST", p + "/preview", preview)
    assert result["evidence"] and all("PRIVATE_SECRET" not in e["text"] for e in result["evidence"])
    assert all(e["metadata"]["assignment_id"] == assignment["id"] for e in result["evidence"])
    await call(client, h, "POST", p + "/preview", {**preview, "selectedPaperId": s["papers"][1]["id"]}, 409)
    overview = await call(client, h, "POST", p + "/preview", {**preview, "selectedPaperId": None})
    assert overview["evidence"] == []
    entry = result["evidence"][0]["entity_id"]
    excerpt = await client.post("/api/v1" + p + f"/preview/excerpts/{entry}", headers=h, json=preview)
    assert excerpt.status_code == 200 and "PRIVATE_SECRET" not in excerpt.text
    await call(
        client,
        h,
        "POST",
        p + f"/versions/{version['id']}/withdraw",
        {"reason": "Source withdrawn by teacher"},
    )
    assert (await call(client, h, "POST", p + "/preview", preview))["evidence"] == []
    revoked = await client.post("/api/v1" + p + f"/preview/excerpts/{entry}", headers=h, json=preview)
    assert revoked.status_code == 404


async def test_changed_mapping_invalidates_approval_and_failed_candidate_preserves_head(client, course_setup):
    s = course_setup
    h, p = s["headers"], s["prefix"]
    version, assignment, body = await source_assignment(client, s)
    _, old_head = await publish(client, s, version, assignment)
    await call(
        client,
        h,
        "POST",
        p + "/releases",
        {
            "courseId": s["course"]["id"],
            "curriculumId": s["curriculum"]["id"],
            "assignmentIds": [str(uuid4())],
        },
        409,
    )
    current = await call(client, h, "GET", p + "/status")
    assert (
        next(row for row in current["heads"] if row["id"] == old_head["id"])["releaseId"]
        == old_head["releaseId"]
    )
    changed = await call(
        client,
        h,
        "PUT",
        p + f"/assignments/{assignment['id']}",
        {**body, "expectedRevision": assignment["revision"], "batchId": s["batch"]["id"]},
    )
    assert changed["status"] == "review" and changed["approvalFingerprint"] is None
    await call(
        client,
        h,
        "POST",
        p + f"/assignments/{assignment['id']}/approve",
        {
            "expectedRevision": assignment["revision"],
            "expectedSourceHash": version["recordHash"],
            "reason": "Stale review must fail",
        },
        409,
    )


async def test_course_selection_does_not_enqueue_processing(client, course_setup):
    from northstar_api.education_student_identities import StudentIdentityType
    from northstar_api.services.course_study_access import authorize_study_access
    from northstar_api.services.education_runtime_authorization import EducationIdentityCandidate

    s = course_setup
    other = await _create_course(client, s["headers"], "CPA-" + uuid4().hex[:10])
    batch = await _create_batch(client, s["headers"], course_id=other["id"], code="CPA-B-" + uuid4().hex[:8])
    enrolled = await _create_enrollment(
        client,
        s["headers"],
        student_id=s["student"]["id"],
        course_id=other["id"],
        batch_id=batch["id"],
        agent_id=s["agent"]["id"],
    )
    curriculum = await call(
        client,
        s["headers"],
        "POST",
        "/education/knowledge/curricula",
        {"courseId": other["id"], "code": "2026", "name": "CPA 2026"},
        201,
    )
    paper = await call(
        client,
        s["headers"],
        "POST",
        "/education/knowledge/papers",
        {"curriculumId": curriculum["id"], "code": "CPA1", "name": "CPA paper"},
        201,
    )
    await call(
        client,
        s["headers"],
        "PUT",
        "/education/knowledge/batch-curriculum",
        {"batchId": batch["id"], "curriculumId": curriculum["id"]},
    )
    await call(
        client,
        s["headers"],
        "PUT",
        s["prefix"] + f"/enrollments/{enrolled['id']}/access",
        {"curriculumId": curriculum["id"], "paperIds": [paper["id"]], "expectedRevision": 0},
    )
    identity = EducationIdentityCandidate(StudentIdentityType.WHATSAPP, s["phone"])
    async with SessionFactory() as session:
        agent = await session.get(Agent, UUID(s["agent"]["id"]))
        job_count = (
            select(func.count())
            .select_from(IngestionJob)
            .join(KnowledgeSource, KnowledgeSource.id == IngestionJob.source_id)
            .where(KnowledgeSource.agent_id == agent.id)
        )
        before = await session.scalar(job_count)
        kwargs = dict(
            tenant_id=agent.tenant_id, workspace_id=agent.workspace_id, agent=agent, identity=identity
        )
        decision, prompt = await authorize_study_access(
            session, **kwargs, message="course " + s["course"]["code"]
        )
        assert decision.authorized and prompt
        await session.commit()
        decision, prompt = await authorize_study_access(session, **kwargs, message="paper P1")
        assert decision.course_id == UUID(s["course"]["id"]) and prompt
        await session.commit()
        decision, prompt = await authorize_study_access(session, **kwargs, message="Explain this lesson")
        assert decision.authorized and prompt is None
        decision, prompt = await authorize_study_access(session, **kwargs, message="course " + other["code"])
        assert decision.authorized and decision.course_id == UUID(other["id"]) and prompt
        await session.commit()
        decision, prompt = await authorize_study_access(session, **kwargs, message="paper CPA1")
        assert decision.enrollment_id == UUID(enrolled["id"]) and prompt
        assert await session.scalar(job_count) == before


async def test_legacy_education_upload_requires_explicit_destination(client, course_setup):
    s = course_setup
    await call(
        client,
        s["headers"],
        "POST",
        f"/agents/{s['agent']['id']}/knowledge",
        {"kind": "text", "name": "Unassigned normal upload", "content": "Must not start processing"},
        409,
    )


async def test_practice_attempts_are_idempotent_and_update_scoped_progress(client, course_setup):
    s = course_setup
    payload = {
        "agentId": s["agent"]["id"],
        "studentId": s["student"]["id"],
        "enrollmentId": s["enrollment"]["id"],
        "paperId": s["papers"][0]["id"],
        "idempotencyKey": "practice-" + uuid4().hex,
        "question": "What is 2 + 2?",
        "answerKey": "4",
    }
    first = await call(client, s["headers"], "POST", "/education/practice/attempts", payload, 201)
    repeated = await call(client, s["headers"], "POST", "/education/practice/attempts", payload, 201)
    assert repeated["id"] == first["id"]

    answered = await call(
        client,
        s["headers"],
        "POST",
        f"/education/practice/attempts/{first['id']}/submit",
        {"studentAnswer": "4"},
    )
    assert answered["isCorrect"] is True

    progress = await call(
        client,
        s["headers"],
        "GET",
        f"/education/progress?enrollment_id={s['enrollment']['id']}&paper_id={s['papers'][0]['id']}",
    )
    assert len(progress) == 1
    assert progress[0]["practiceAttempts"] == 1
    assert progress[0]["objectiveAnswersCorrect"] == 1
    assert progress[0]["objectiveAnswersGraded"] == 1


async def test_course_syllabus_is_created_once_and_reused(client, course_setup):
    s = course_setup
    existing = await call(client, s["headers"], "POST", f"/education/knowledge/courses/{s['course']['id']}/curriculum")
    assert existing["id"] == s["curriculum"]["id"]  # a course that has one keeps using it
    fresh = await _create_course(client, s["headers"], "NEW-" + uuid4().hex[:10])
    first = await call(client, s["headers"], "POST", f"/education/knowledge/courses/{fresh['id']}/curriculum")
    second = await call(client, s["headers"], "POST", f"/education/knowledge/courses/{fresh['id']}/curriculum")
    assert first["id"] == second["id"] and first["code"] == "DEFAULT" and first["name"].endswith("syllabus")
    await call(client, s["headers"], "POST", f"/education/knowledge/courses/{uuid4()}/curriculum", expected=404)


async def test_upload_to_a_batch_links_it_to_the_course_syllabus(client, course_setup):
    """Batches are not linked to a syllabus by hand any more: an unlinked batch of the course is
    linked on first use instead of the upload being refused."""
    s = course_setup
    course = await _create_course(client, s["headers"], "LNK-" + uuid4().hex[:10])
    batch = await _create_batch(client, s["headers"], course_id=course["id"], code="LB-" + uuid4().hex[:8])
    # Syllabus created by hand (as older setups did), so nothing linked the batch yet.
    curriculum = await call(client, s["headers"], "POST", "/education/knowledge/curricula",
                            {"courseId": course["id"], "code": "2026", "name": "Syllabus"}, 201)
    body = {"idempotencyKey": str(uuid4()), "title": "Batch notes", "kind": "text", "content": "Batch lesson",
            "destination": {"courseId": course["id"], "curriculumId": curriculum["id"], "overview": True, "batchId": batch["id"]}}
    uploaded = await call(client, s["headers"], "POST", s["prefix"] + "/uploads", body, 201)
    assert uploaded["sourceId"]
    catalog = await call(client, s["headers"], "GET", "/education/knowledge/catalog")
    assert {"batchId": batch["id"], "curriculumId": curriculum["id"]}.items() <= next(
        b for b in catalog["batchCurricula"] if b["batchId"] == batch["id"]).items()


async def test_course_syllabus_links_the_course_batches(client, course_setup):
    s = course_setup
    course = await _create_course(client, s["headers"], "SYL-" + uuid4().hex[:10])
    batch = await _create_batch(client, s["headers"], course_id=course["id"], code="SB-" + uuid4().hex[:8])
    syllabus = await call(client, s["headers"], "POST", f"/education/knowledge/courses/{course['id']}/curriculum")
    catalog = await call(client, s["headers"], "GET", "/education/knowledge/catalog")
    link = next(b for b in catalog["batchCurricula"] if b["batchId"] == batch["id"])
    assert link["curriculumId"] == syllabus["id"]


async def _stream(client, headers, agent_id, conversation_id, message):
    response = await client.post("/api/v1/chat/stream", headers=headers, json={
        "agentId": agent_id, "conversationId": conversation_id, "message": message, "idempotencyKey": str(uuid4())})
    text = ""
    for line in response.text.splitlines():  # join the streamed reply back into one string
        if line.startswith("data: {"):
            event = json.loads(line[6:])
            text += event.get("content") or event.get("delta") or ""
    return response.status_code, text


async def test_staff_can_test_chat_as_a_student_before_publishing(client, course_setup):
    s = course_setup
    h, p = s["headers"], s["prefix"]
    candidates = await call(client, h, "GET", p + "/test-conversations/candidates")
    mine = next(c for c in candidates if c["enrollmentId"] == s["enrollment"]["id"])
    assert mine["ready"] and not mine["hasPublishedRelease"]

    # Approved and indexed, but not published yet.
    version, assignment, _ = await source_assignment(client, s)
    await call(client, h, "POST", p + f"/assignments/{assignment['id']}/approve", {
        "expectedRevision": assignment["revision"], "expectedSourceHash": version["recordHash"],
        "reason": "Checked against the original"})
    await call(client, h, "POST", p + f"/assignments/{assignment['id']}/prepare", {"expectedRevision": assignment["revision"]}, 202)

    live = await call(client, h, "POST", p + "/test-conversations", {"enrollmentId": s["enrollment"]["id"]}, 201)
    assert live["mode"] == "published" and "Nothing is published" in live["notice"]
    status, body = await _stream(client, h, s["agent"]["id"], live["conversationId"], "Paper A approved lesson")
    assert status == 200, body
    assert "Paper A approved lesson. [S1]" not in body  # a real student would get no course answer yet

    draft = await call(client, h, "POST", p + "/test-conversations",
                       {"enrollmentId": s["enrollment"]["id"], "includeUnpublished": True}, 201)
    assert draft["mode"] == "unpublished"
    status, body = await _stream(client, h, s["agent"]["id"], draft["conversationId"], "Paper A approved lesson")
    assert status == 200, body
    assert "Paper A approved lesson. [S1]" in body  # answered from approved, unpublished material


async def test_no_course_evidence_obeys_each_internet_policy_and_opens_review(client, course_setup, monkeypatch):
    from northstar_api.modules.knowledge.retrieval import Evidence
    from northstar_api.services import course_knowledge_chat

    s = course_setup
    calls = []

    async def web_evidence(query, domains, *, allow_public):
        calls.append((query, domains, allow_public))
        return [Evidence("web", "verified-web", None, "Verified reference",
            "https://example.edu/lesson", "Paper A approved lesson", 1.0)]

    monkeypatch.setattr(course_knowledge_chat, "related_web_evidence", web_evidence)
    for policy in ("none", "allowlisted", "public"):
        async with SessionFactory() as session:
            agent = await session.get(Agent, UUID(s["agent"]["id"]))
            agent.model_profile = {**(agent.model_profile or {}), "internetAccess": policy}
            agent.security = {**(agent.security or {}), "webAllowedDomains": ["example.edu"]}
            await session.commit()
        live = await call(client, s["headers"], "POST", s["prefix"] + "/test-conversations",
            {"enrollmentId": s["enrollment"]["id"]}, 201)
        status, body = await _stream(client, s["headers"], s["agent"]["id"], live["conversationId"],
            "Paper A approved lesson")
        assert status == 200, body
        if policy == "none":
            assert calls == [] and "not published" in body.lower()
        else:
            assert "external web information" in body.lower() and "https://example.edu/lesson" in body
            assert calls[-1][2] is (policy == "public")
    reviews = await call(client, s["headers"], "GET",
        f"/education/academic-reviews?agent_id={s['agent']['id']}")
    assert any(review["reason"] == "no_authorized_published_evidence" for review in reviews)
    async with SessionFactory() as session:
        agent = await session.get(Agent, UUID(s["agent"]["id"]))
        agent.security = {**(agent.security or {}), "blockedTopics": ["Paper A approved lesson"]}
        await session.commit()
    live = await call(client, s["headers"], "POST", s["prefix"] + "/test-conversations",
        {"enrollmentId": s["enrollment"]["id"]}, 201)
    status, body = await _stream(client, s["headers"], s["agent"]["id"], live["conversationId"],
        "Explain this syllabus")
    assert status == 200 and "Paper A approved lesson" not in body
    assert "can't help with that request" in body


async def test_test_chat_rejects_an_enrollment_that_cannot_be_tutored(client, course_setup):
    s = course_setup
    other = await _create_course(client, s["headers"], "NOA-" + uuid4().hex[:10])
    batch = await _create_batch(client, s["headers"], course_id=other["id"], code="NB-" + uuid4().hex[:8])
    enrollment = await _create_enrollment(client, s["headers"], student_id=s["student"]["id"], course_id=other["id"],
                                          batch_id=batch["id"], agent_id=s["agent"]["id"])
    candidates = await call(client, s["headers"], "GET", s["prefix"] + "/test-conversations/candidates")
    blocked = next(c for c in candidates if c["enrollmentId"] == enrollment["id"])
    assert not blocked["ready"] and blocked["reason"]
    await call(client, s["headers"], "POST", s["prefix"] + "/test-conversations", {"enrollmentId": enrollment["id"]}, expected=409)
