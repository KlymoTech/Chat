from __future__ import annotations

from httpx import AsyncClient


async def test_non_terminal_enrollment_protects_student_course_batch_and_agent(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    workspace_id = workspace.json()["id"]
    headers = {**auth_headers, "X-Workspace-ID": workspace_id}

    course_response = await client.post(
        "/api/v1/education/courses",
        headers=headers,
        json={"code": "ENR-GUARD", "name": "Enrollment Guard Course"},
    )
    assert course_response.status_code == 201, course_response.text
    course = course_response.json()

    batch_response = await client.post(
        "/api/v1/education/batches",
        headers=headers,
        json={
            "courseId": course["id"],
            "code": "ENR-GUARD-A",
            "name": "Enrollment Guard Batch",
        },
    )
    assert batch_response.status_code == 201, batch_response.text
    batch = batch_response.json()

    student_response = await client.post(
        "/api/v1/education/students",
        headers=headers,
        json={"studentNumber": "ENR-GUARD-1", "name": "Guard Student"},
    )
    assert student_response.status_code == 201, student_response.text
    student = student_response.json()

    agent_response = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": "Enrollment Guard Education Agent",
            "description": "Guarded by enrollment dependencies",
            "purpose": "education",
            "deploymentChannel": "website",
        },
    )
    assert agent_response.status_code == 201, agent_response.text
    agent = agent_response.json()

    activate_before_enrollment = await client.patch(
        f"/api/v1/agents/{agent['id']}",
        headers=headers,
        json={"status": "active"},
    )
    assert activate_before_enrollment.status_code == 409, activate_before_enrollment.text

    enrollment_response = await client.post(
        "/api/v1/education/enrollments",
        headers=headers,
        json={
            "studentId": student["id"],
            "courseId": course["id"],
            "batchId": batch["id"],
            "agentId": agent["id"],
            "status": "active",
        },
    )
    assert enrollment_response.status_code == 201, enrollment_response.text
    enrollment = enrollment_response.json()

    activate_after_enrollment = await client.patch(
        f"/api/v1/agents/{agent['id']}",
        headers=headers,
        json={"status": "active"},
    )
    assert activate_after_enrollment.status_code == 200, activate_after_enrollment.text

    archive_student = await client.delete(
        f"/api/v1/education/students/{student['id']}",
        headers=headers,
    )
    assert archive_student.status_code == 409, archive_student.text

    archive_batch = await client.delete(
        f"/api/v1/education/batches/{batch['id']}",
        headers=headers,
    )
    assert archive_batch.status_code == 409, archive_batch.text

    archive_course = await client.delete(
        f"/api/v1/education/courses/{course['id']}",
        headers=headers,
    )
    assert archive_course.status_code == 409, archive_course.text

    change_agent_purpose = await client.patch(
        f"/api/v1/agents/{agent['id']}",
        headers=headers,
        json={"purpose": "support"},
    )
    assert change_agent_purpose.status_code == 409, change_agent_purpose.text

    delete_agent = await client.delete(f"/api/v1/agents/{agent['id']}", headers=headers)
    assert delete_agent.status_code == 409, delete_agent.text

    graduate = await client.patch(
        f"/api/v1/education/enrollments/{enrollment['id']}",
        headers=headers,
        json={"status": "graduated"},
    )
    assert graduate.status_code == 200, graduate.text

    change_after_terminal = await client.patch(
        f"/api/v1/agents/{agent['id']}",
        headers=headers,
        json={"purpose": "support", "status": "draft"},
    )
    assert change_after_terminal.status_code == 200, change_after_terminal.text
    assert change_after_terminal.json()["purpose"] == "support"

    archive_student_after_terminal = await client.delete(
        f"/api/v1/education/students/{student['id']}",
        headers=headers,
    )
    assert archive_student_after_terminal.status_code == 204, archive_student_after_terminal.text

    archive_batch_after_terminal = await client.delete(
        f"/api/v1/education/batches/{batch['id']}",
        headers=headers,
    )
    assert archive_batch_after_terminal.status_code == 204, archive_batch_after_terminal.text

    archive_course_after_terminal = await client.delete(
        f"/api/v1/education/courses/{course['id']}",
        headers=headers,
    )
    assert archive_course_after_terminal.status_code == 204, archive_course_after_terminal.text


async def test_permanent_student_delete_removes_active_enrollments_only(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    course_response = await client.post(
        "/api/v1/education/courses",
        headers=auth_headers,
        json={"code": "DELETE-STUDENT", "name": "Permanent Delete Course"},
    )
    assert course_response.status_code == 201, course_response.text
    course = course_response.json()
    batch_response = await client.post(
        "/api/v1/education/batches",
        headers=auth_headers,
        json={"courseId": course["id"], "code": "DELETE-STUDENT-A", "name": "Delete Batch"},
    )
    assert batch_response.status_code == 201, batch_response.text
    batch = batch_response.json()
    student_response = await client.post(
        "/api/v1/education/students",
        headers=auth_headers,
        json={
            "studentNumber": "DELETE-STUDENT-1",
            "name": "Delete Me",
            "telegramUserId": "88332211",
            "telegramVerified": True,
        },
    )
    assert student_response.status_code == 201, student_response.text
    student = student_response.json()
    agent_response = await client.post(
        "/api/v1/agents",
        headers=auth_headers,
        json={
            "name": "Permanent Delete Education Agent",
            "description": "Only used for a delete test",
            "purpose": "education",
            "deploymentChannel": "website",
        },
    )
    assert agent_response.status_code == 201, agent_response.text
    agent = agent_response.json()
    enrollment_response = await client.post(
        "/api/v1/education/enrollments",
        headers=auth_headers,
        json={
            "studentId": student["id"],
            "courseId": course["id"],
            "batchId": batch["id"],
            "agentId": agent["id"],
            "status": "active",
        },
    )
    assert enrollment_response.status_code == 201, enrollment_response.text

    deleted = await client.delete(
        f"/api/v1/education/students/{student['id']}/permanent",
        headers=auth_headers,
    )
    assert deleted.status_code == 204, deleted.text

    assert (await client.get(f"/api/v1/education/students/{student['id']}", headers=auth_headers)).status_code == 404
    enrollments = await client.get("/api/v1/education/enrollments", headers=auth_headers)
    assert enrollments.status_code == 200, enrollments.text
    assert all(item["studentId"] != student["id"] for item in enrollments.json())
    assert (await client.get(f"/api/v1/education/courses/{course['id']}", headers=auth_headers)).status_code == 200
    assert (await client.get(f"/api/v1/education/batches/{batch['id']}", headers=auth_headers)).status_code == 200


async def test_permanent_course_delete_removes_its_batches_and_enrollments_only(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    course_response = await client.post(
        "/api/v1/education/courses",
        headers=auth_headers,
        json={"code": "DELETE-COURSE", "name": "Delete Course"},
    )
    assert course_response.status_code == 201, course_response.text
    course = course_response.json()
    batch_response = await client.post(
        "/api/v1/education/batches",
        headers=auth_headers,
        json={"courseId": course["id"], "code": "DELETE-COURSE-A", "name": "Delete Course Batch"},
    )
    assert batch_response.status_code == 201, batch_response.text
    batch = batch_response.json()
    student_response = await client.post(
        "/api/v1/education/students",
        headers=auth_headers,
        json={"studentNumber": "DELETE-COURSE-1", "name": "Keep This Student"},
    )
    assert student_response.status_code == 201, student_response.text
    student = student_response.json()
    agent_response = await client.post(
        "/api/v1/agents",
        headers=auth_headers,
        json={
            "name": "Course Delete Education Agent",
            "description": "Only used for a course delete test",
            "purpose": "education",
            "deploymentChannel": "website",
        },
    )
    assert agent_response.status_code == 201, agent_response.text
    agent = agent_response.json()
    enrollment_response = await client.post(
        "/api/v1/education/enrollments",
        headers=auth_headers,
        json={
            "studentId": student["id"],
            "courseId": course["id"],
            "batchId": batch["id"],
            "agentId": agent["id"],
            "status": "active",
        },
    )
    assert enrollment_response.status_code == 201, enrollment_response.text
    enrollment = enrollment_response.json()

    deleted = await client.delete(
        f"/api/v1/education/courses/{course['id']}/permanent",
        headers=auth_headers,
    )
    assert deleted.status_code == 204, deleted.text

    assert (await client.get(f"/api/v1/education/courses/{course['id']}", headers=auth_headers)).status_code == 404
    assert (await client.get(f"/api/v1/education/batches/{batch['id']}", headers=auth_headers)).status_code == 404
    assert (await client.get(f"/api/v1/education/students/{student['id']}", headers=auth_headers)).status_code == 200
    assert (await client.get(f"/api/v1/agents/{agent['id']}", headers=auth_headers)).status_code == 200
    enrollments = await client.get("/api/v1/education/enrollments", headers=auth_headers)
    assert enrollments.status_code == 200, enrollments.text
    assert all(item["id"] != enrollment["id"] for item in enrollments.json())
