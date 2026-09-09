from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.education_student_schemas import StudentCreate, StudentOut, StudentPatch
from northstar_api.education_students import EducationStudent, StudentStatus
from northstar_api.security import Principal
from northstar_api.services.outbox import enqueue_event

router = APIRouter(prefix="/education/students", tags=["education"])
DB = Annotated[AsyncSession, Depends(get_session)]
EducationViewPrincipal = Annotated[Principal, Depends(require_permissions("education.view"))]
EducationManagePrincipal = Annotated[Principal, Depends(require_permissions("education.manage"))]


def _workspace_id(principal: Principal) -> UUID:
    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")
    return principal.workspace_id


async def _scoped_student(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    student_id: UUID,
) -> EducationStudent:
    student = await session.scalar(
        select(EducationStudent).where(
            EducationStudent.id == student_id,
            EducationStudent.tenant_id == tenant_id,
            EducationStudent.workspace_id == workspace_id,
        )
    )
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


def _student_out(student: EducationStudent) -> StudentOut:
    return StudentOut.model_validate(student)


@router.get("", response_model=list[StudentOut])
async def list_students(
    principal: EducationViewPrincipal,
    session: DB,
    student_status: StudentStatus | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=160),
) -> list[StudentOut]:
    workspace_id = _workspace_id(principal)
    conditions = [
        EducationStudent.tenant_id == principal.tenant_id,
        EducationStudent.workspace_id == workspace_id,
    ]
    if student_status is not None:
        conditions.append(EducationStudent.status == student_status.value)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                EducationStudent.student_number.ilike(pattern),
                EducationStudent.name.ilike(pattern),
                EducationStudent.email.ilike(pattern),
            )
        )
    students = (
        await session.scalars(
            select(EducationStudent)
            .where(*conditions)
            .order_by(EducationStudent.status, EducationStudent.name, EducationStudent.student_number)
        )
    ).all()
    return [_student_out(student) for student in students]


@router.post("", response_model=StudentOut, status_code=201)
async def create_student(
    payload: StudentCreate,
    principal: EducationManagePrincipal,
    session: DB,
) -> StudentOut:
    workspace_id = _workspace_id(principal)
    student = EducationStudent(
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        student_number=payload.student_number,
        name=payload.name,
        email=str(payload.email) if payload.email is not None else None,
        custom_fields=payload.custom_fields,
        status=StudentStatus.ACTIVE.value,
    )
    session.add(student)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A student with this Student ID already exists in this workspace",
        ) from None
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="education_student",
        aggregate_id=student.id,
        event_type="education.student.created.v1",
        payload={
            "studentId": str(student.id),
            "workspaceId": str(workspace_id),
            "studentNumber": student.student_number,
            "name": student.name,
        },
    )
    await session.commit()
    await session.refresh(student)
    return _student_out(student)


@router.get("/{student_id}", response_model=StudentOut)
async def get_student(
    student_id: UUID,
    principal: EducationViewPrincipal,
    session: DB,
) -> StudentOut:
    return _student_out(
        await _scoped_student(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=_workspace_id(principal),
            student_id=student_id,
        )
    )


@router.patch("/{student_id}", response_model=StudentOut)
async def update_student(
    student_id: UUID,
    payload: StudentPatch,
    principal: EducationManagePrincipal,
    session: DB,
) -> StudentOut:
    student = await _scoped_student(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=_workspace_id(principal),
        student_id=student_id,
    )
    changed_fields: list[str] = []
    for field_name in payload.model_fields_set:
        value = getattr(payload, field_name)
        if field_name == "status" and value is not None:
            value = value.value
        if field_name == "email" and value is not None:
            value = str(value)
        if getattr(student, field_name) == value:
            continue
        setattr(student, field_name, value)
        changed_fields.append(field_name)

    if not changed_fields:
        return _student_out(student)

    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="education_student",
        aggregate_id=student.id,
        event_type="education.student.updated.v1",
        payload={
            "studentId": str(student.id),
            "workspaceId": str(student.workspace_id),
            "fields": sorted(changed_fields),
            "status": student.status,
        },
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A student with this Student ID already exists in this workspace",
        ) from None
    await session.refresh(student)
    return _student_out(student)


@router.delete("/{student_id}", status_code=204)
async def archive_student(
    student_id: UUID,
    principal: EducationManagePrincipal,
    session: DB,
) -> Response:
    student = await _scoped_student(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=_workspace_id(principal),
        student_id=student_id,
    )
    if student.status != StudentStatus.ARCHIVED.value:
        student.status = StudentStatus.ARCHIVED.value
        enqueue_event(
            session,
            tenant_id=principal.tenant_id,
            aggregate_type="education_student",
            aggregate_id=student.id,
            event_type="education.student.archived.v1",
            payload={
                "studentId": str(student.id),
                "workspaceId": str(student.workspace_id),
                "studentNumber": student.student_number,
            },
        )
        await session.commit()
    return Response(status_code=204)
