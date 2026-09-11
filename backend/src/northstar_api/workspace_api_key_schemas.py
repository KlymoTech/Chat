from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from northstar_api.schemas import APIModel


class WorkspaceAPIKeyCreate(APIModel):
    name: str = Field(min_length=2, max_length=120)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("must contain at least two visible characters")
        return normalized


class WorkspaceAPIKeyOut(APIModel):
    id: UUID
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None = None


class WorkspaceAPIKeyCreated(WorkspaceAPIKeyOut):
    secret: str
