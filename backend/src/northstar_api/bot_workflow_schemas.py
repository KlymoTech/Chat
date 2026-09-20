from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from northstar_api.agent_purpose import AgentPurpose
from northstar_api.schemas import APIModel


class WorkflowButton(APIModel):
    id: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=20)


class WorkflowTable(APIModel):
    columns: list[str] = Field(default_factory=list, max_length=5)
    rows: list[list[str]] = Field(default_factory=list, max_length=20)


class WorkflowTemplate(APIModel):
    name: str = Field(min_length=1, max_length=512)
    language: str = Field(min_length=2, max_length=20)
    preview: str = Field(default="", max_length=12_000)


class BotWorkflowStep(APIModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=120)
    trigger_type: Literal["command", "contains", "fallback"]
    trigger_value: str = Field(default="", max_length=240)
    message_format: Literal["text", "buttons", "table", "template"] = "text"
    message: str = Field(min_length=1, max_length=12_000)
    buttons: list[WorkflowButton] = Field(default_factory=list, max_length=3)
    table: WorkflowTable | None = None
    template: WorkflowTemplate | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def validate_format(self) -> BotWorkflowStep:
        if self.trigger_type != "fallback" and not self.trigger_value.strip():
            raise ValueError("Command and keyword triggers require a value")
        if self.message_format == "buttons" and not self.buttons:
            raise ValueError("Button steps require at least one button")
        if self.message_format == "buttons" and len(self.message) > 1024:
            raise ValueError("WhatsApp button message bodies cannot exceed 1024 characters")
        if self.message_format == "table" and (
            not self.table or not self.table.columns or not self.table.rows
            or any(len(row) != len(self.table.columns) for row in self.table.rows)
        ):
            raise ValueError("Table steps require matching columns and rows")
        if self.message_format == "template" and not self.template:
            raise ValueError("Template steps require an approved template selection")
        return self


class BotWorkflowSave(APIModel):
    name: str = Field(min_length=2, max_length=160)
    purpose: AgentPurpose
    status: Literal["draft", "active"] = "draft"
    steps: list[BotWorkflowStep] = Field(default_factory=list, max_length=50)

    @field_validator("steps")
    @classmethod
    def unique_steps(cls, steps: list[BotWorkflowStep]) -> list[BotWorkflowStep]:
        if len({step.id for step in steps}) != len(steps):
            raise ValueError("Workflow step IDs must be unique")
        if sum(step.trigger_type == "fallback" and step.enabled for step in steps) > 1:
            raise ValueError("Only one enabled fallback step is allowed")
        return steps


class BotWorkflowOut(BotWorkflowSave):
    id: UUID
    agent_id: UUID
    created_at: datetime
    updated_at: datetime
