from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from northstar_api.education import CourseStatus
from northstar_api.schemas import APIModel

_COURSE_CODE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,39}$")


def _normalize_code(value: str) -> str:
    normalized = value.strip().upper()
    if not _COURSE_CODE.fullmatch(normalized):
        raise ValueError("course code must use letters, numbers, dots, dashes, or underscores")
    return normalized


def _normalize_name(value: str) -> str:
    normalized = value.strip()
    if len(normalized) < 2:
        raise ValueError("course name must contain at least 2 characters")
    return normalized


class CourseCreate(APIModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=2000)

    @field_validator("code")
    @classmethod
    def valid_code(cls, value: str) -> str:
        return _normalize_code(value)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        return _normalize_name(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()


class CoursePatch(APIModel):
    code: str | None = Field(default=None, min_length=1, max_length=40)
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    status: CourseStatus | None = None

    @field_validator("code")
    @classmethod
    def valid_code(cls, value: str | None) -> str | None:
        return _normalize_code(value) if value is not None else None

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str | None) -> str | None:
        return _normalize_name(value) if value is not None else None

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class CourseOut(APIModel):
    id: UUID
    tenant_id: UUID
    workspace_id: UUID
    code: str
    name: str
    description: str
    status: CourseStatus
    created_at: datetime
    updated_at: datetime
