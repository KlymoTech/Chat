from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.models import BotWorkflow


@dataclass(frozen=True, slots=True)
class WorkflowReply:
    content: str
    message_format: dict[str, Any]


def _matches(step: dict[str, Any], incoming: str) -> bool:
    trigger = str(step.get("triggerValue") or step.get("trigger_value") or "").strip().casefold()
    kind = step.get("triggerType") or step.get("trigger_type")
    normalized = incoming.strip().casefold()
    if kind == "fallback":
        return True
    if kind == "command":
        return normalized == trigger or normalized == trigger.lstrip("/")
    return bool(trigger and trigger in normalized)


def _render(step: dict[str, Any]) -> WorkflowReply:
    kind = str(step.get("messageFormat") or step.get("message_format") or "text")
    body = str(step.get("message") or "").strip()
    payload: dict[str, Any] = {"type": kind, "workflowStepId": step.get("id")}
    payload["config"] = step.get("config") or {}
    if kind == "buttons":
        buttons = list(step.get("buttons") or [])
        payload["buttons"] = buttons
        return WorkflowReply(body, payload)
    if kind == "table":
        table = step.get("table") or {}
        columns = list(table.get("columns") or [])
        rows = list(table.get("rows") or [])
        payload.update({"body": body, "table": {"columns": columns, "rows": rows}})
        lines = [" | ".join(columns), " | ".join("---" for _ in columns)]
        lines.extend(" | ".join(str(cell) for cell in row) for row in rows)
        return WorkflowReply(f"{body}\n\n" + "\n".join(lines), payload)
    if kind == "template":
        payload["template"] = step.get("template")
        payload["type"] = "template"
        return WorkflowReply(body, payload)
    payload["type"] = kind
    return WorkflowReply(body or f"[{kind.replace('_', ' ')}]", payload)


async def match_bot_workflow(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    agent_id: UUID,
    message: str,
    channel: str = "widget",
) -> WorkflowReply | None:
    workflow = await session.scalar(
        select(BotWorkflow).where(
            BotWorkflow.tenant_id == tenant_id,
            BotWorkflow.workspace_id == workspace_id,
            BotWorkflow.agent_id == agent_id,
            BotWorkflow.status == "active",
        )
    )
    if not workflow:
        return None
    enabled = [step for step in (workflow.steps_json or []) if step.get("enabled", True)]
    fallback = None
    by_id = {str(step.get("id")): step for step in enabled}
    for step in enabled:
        kind = step.get("triggerType") or step.get("trigger_type")
        if kind == "fallback":
            fallback = step
        elif kind == "condition":
            condition = step.get("condition") or {}
            actual = channel if condition.get("field") == "channel" else message
            expected = str(condition.get("value") or "").casefold()
            actual_normalized = actual.casefold()
            operator = condition.get("operator")
            matched = (
                actual_normalized == expected
                if operator == "equals"
                else actual_normalized.startswith(expected)
                if operator == "starts_with"
                else expected not in actual_normalized
                if operator == "not_contains"
                else expected in actual_normalized
            )
            target = (
                step.get("trueStepId") or step.get("true_step_id")
                if matched
                else step.get("falseStepId") or step.get("false_step_id")
            )
            if target and str(target) in by_id:
                return _render(by_id[str(target)])
        elif _matches(step, message):
            return _render(step)
    return _render(fallback) if fallback else None
