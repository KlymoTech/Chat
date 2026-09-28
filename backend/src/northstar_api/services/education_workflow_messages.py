"""Safe, backend-triggered Education workflow copy.

These are message templates, never permission or retrieval decisions. Unknown
placeholders fail back to backend copy rather than leaking unresolved tokens.
"""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import select

from northstar_api.models import BotWorkflow

_PLACEHOLDER = re.compile(r"{{\s*([a-z_]+)\s*}}")


async def education_workflow_message(session, *, tenant_id: UUID, workspace_id: UUID,
    agent_id: UUID, action: str, default: str, values: dict[str, str] | None = None) -> str:
    workflow = await session.scalar(select(BotWorkflow).where(
        BotWorkflow.tenant_id == tenant_id, BotWorkflow.workspace_id == workspace_id,
        BotWorkflow.agent_id == agent_id, BotWorkflow.status == "active",
    ))
    if workflow is None:
        return default
    step = next((item for item in workflow.steps_json or [] if item.get("enabled", True)
        and item.get("triggerType") == "event"
        and (item.get("config") or {}).get("systemAction") == action), None)
    if step is None:
        return default
    template = str(step.get("message") or "").strip()
    allowed = values or {}
    if not template or any(key not in allowed for key in _PLACEHOLDER.findall(template)):
        return default
    return _PLACEHOLDER.sub(lambda match: allowed[match.group(1)], template)
