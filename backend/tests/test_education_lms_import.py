from __future__ import annotations

import pytest
from pydantic import ValidationError

from northstar_api.education_lms_import_schemas import (
    LMSStudentImportPayload,
    LMSStudentImportRow,
    to_student_import_rows,
)
from northstar_api.education_student_identities import StudentIdentityType


def test_lms_import_maps_into_existing_student_import_contract() -> None:
    payload = LMSStudentImportPayload(
        source="Canvas LMS",
        rows=[
            LMSStudentImportRow(
                external_student_id=" stu-1001 ",
                name="  Ada   Lovelace ",
                email="ADA@example.com",
                identity_type=StudentIdentityType.WEBSITE_LOGIN,
                identifier="ada.lovelace",
                identity_verified=True,
                course_code="cpa",
                batch_code="jan-2027",
                agent_public_id="agent_education",
                external_course_id="course-42",
                external_batch_id="section-7",
                custom_fields={"campus": "Patna"},
            )
        ],
    )

    rows = to_student_import_rows(payload)

    assert len(rows) == 1
    row = rows[0]
    assert row.student_number == "STU-1001"
    assert row.name == "Ada Lovelace"
    assert row.email == "ada@example.com"
    assert row.course_code == "CPA"
    assert row.batch_code == "JAN-2027"
    assert row.identity_type == StudentIdentityType.WEBSITE_LOGIN
    assert row.identity_verified is True
    assert row.custom_fields == {
        "campus": "Patna",
        "lms_source": "canvas_lms",
        "lms_student_id": "stu-1001",
        "lms_course_id": "course-42",
        "lms_batch_id": "section-7",
    }


def test_lms_import_does_not_override_explicit_lms_custom_fields() -> None:
    payload = LMSStudentImportPayload(
        source="Moodle",
        rows=[
            LMSStudentImportRow(
                external_student_id="M-1",
                name="Grace Hopper",
                custom_fields={
                    "lms_source": "custom_source",
                    "lms_student_id": "custom_student",
                },
            )
        ],
    )

    row = to_student_import_rows(payload)[0]

    assert row.custom_fields["lms_source"] == "custom_source"
    assert row.custom_fields["lms_student_id"] == "custom_student"


def test_lms_import_requires_identity_pair() -> None:
    with pytest.raises(ValidationError, match="identity type and identifier"):
        LMSStudentImportRow(
            external_student_id="M-2",
            name="Katherine Johnson",
            identifier="katherine",
        )


def test_lms_import_reuses_existing_enrollment_group_validation() -> None:
    payload = LMSStudentImportPayload(
        source="Blackboard",
        rows=[
            LMSStudentImportRow(
                external_student_id="B-1",
                name="Dorothy Vaughan",
                course_code="CPA",
            )
        ],
    )

    with pytest.raises(ValidationError, match="Course, Batch, and Agent"):
        to_student_import_rows(payload)
