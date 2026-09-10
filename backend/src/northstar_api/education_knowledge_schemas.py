from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from northstar_api.schemas import APIModel


class EducationKnowledgeScopeRef(APIModel):
    course_id: UUID
    batch_id: UUID


class EducationKnowledgeScopeReplace(APIModel):
    scopes: list[EducationKnowledgeScopeRef] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_pairs(self) -> EducationKnowledgeScopeReplace:
        pairs = {(item.course_id, item.batch_id) for item in self.scopes}
        if len(pairs) != len(self.scopes):
            raise ValueError("education knowledge scopes must be unique")
        return self


class EducationKnowledgeScopeOut(EducationKnowledgeScopeRef):
    id: UUID
    source_id: UUID | None = None
    fact_id: UUID | None = None
    agent_id: UUID
    workspace_id: UUID
    created_at: datetime
    updated_at: datetime
