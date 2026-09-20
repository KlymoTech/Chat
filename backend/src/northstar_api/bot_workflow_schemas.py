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


class WorkflowCondition(APIModel):
    field: Literal["message", "channel"] = "message"
    operator: Literal["equals", "contains", "not_contains", "starts_with"] = "contains"
    value: str = Field(min_length=1, max_length=240)


class BotWorkflowStep(APIModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=120)
    trigger_type: Literal["command", "contains", "condition", "fallback"]
    trigger_value: str = Field(default="", max_length=240)
    message_format: Literal[
        "text",
        "buttons",
        "list",
        "table",
        "image",
        "video",
        "audio",
        "document",
        "sticker",
        "location",
        "contact",
        "cta_url",
        "flow",
        "product",
        "product_list",
        "catalog",
        "template",
    ] = "text"
    message: str = Field(default="", max_length=12_000)
    buttons: list[WorkflowButton] = Field(default_factory=list, max_length=3)
    table: WorkflowTable | None = None
    template: WorkflowTemplate | None = None
    config: dict[str, object] = Field(default_factory=dict)
    condition: WorkflowCondition | None = None
    true_step_id: str | None = Field(default=None, max_length=80)
    false_step_id: str | None = Field(default=None, max_length=80)
    next_step_id: str | None = Field(default=None, max_length=80)
    position_x: int = Field(default=40, ge=0, le=5000)
    position_y: int = Field(default=40, ge=0, le=5000)
    bot_behavior: Literal["complete", "wait_for_next_trigger"] = "complete"
    waiting_message: str = Field(default="Please choose an option or send the next command.", max_length=1024)
    wait_repeat_count: int = Field(default=0, ge=0, le=10)
    repeat_policy: Literal[
        "every_match", "once_per_conversation", "once_per_24_hours", "once_per_calendar_day"
    ] = "every_match"
    max_sends: int | None = Field(default=None, ge=1, le=100)
    cooldown_minutes: int = Field(default=0, ge=0, le=43_200)
    calendar_timezone: str = Field(default="Asia/Kolkata", min_length=1, max_length=64)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_format(self) -> BotWorkflowStep:
        if self.message_format == "buttons" and len(self.message) > 1024:
            raise ValueError("WhatsApp button message bodies cannot exceed 1024 characters")
        if self.bot_behavior == "wait_for_next_trigger" and not self.waiting_message.strip():
            raise ValueError("A waiting message is required while the bot remains active")
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(self.calendar_timezone)
        except (KeyError, ValueError):
            raise ValueError("calendar_timezone must be a valid IANA timezone") from None
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

    @model_validator(mode="after")
    def validate_active_steps(self) -> BotWorkflowSave:
        if self.status != "active":
            return self
        ids = {step.id for step in self.steps if step.enabled}
        optional_body = {"audio", "sticker", "location", "contact", "product", "product_list", "catalog"}
        for step in self.steps:
            if not step.enabled:
                continue
            if step.trigger_type not in {"fallback", "condition"} and not step.trigger_value.strip():
                raise ValueError(f"{step.name}: command and keyword triggers require a value")
            if step.trigger_type == "condition":
                if not step.condition or not step.true_step_id or step.true_step_id not in ids:
                    raise ValueError(f"{step.name}: condition requires a valid true branch")
                continue
            if step.next_step_id and step.next_step_id not in ids:
                raise ValueError(f"{step.name}: next step must reference an enabled workflow step")
            if step.message_format not in optional_body and not step.message.strip():
                raise ValueError(f"{step.name}: response message is required")
            if step.message_format == "buttons" and not step.buttons:
                raise ValueError(f"{step.name}: add at least one button")
            if step.message_format == "table" and (
                not step.table
                or not step.table.columns
                or not step.table.rows
                or any(len(row) != len(step.table.columns) for row in step.table.rows)
            ):
                raise ValueError(f"{step.name}: table requires matching columns and rows")
            if step.message_format == "template" and not step.template:
                raise ValueError(f"{step.name}: select an approved template")
        return self


class BotWorkflowOut(BotWorkflowSave):
    id: UUID
    agent_id: UUID
    created_at: datetime
    updated_at: datetime
