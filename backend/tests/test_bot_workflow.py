from __future__ import annotations

import pytest
from pydantic import ValidationError

from northstar_api.bot_workflow_schemas import BotWorkflowStep
from northstar_api.services.bot_workflows import _matches, _render


def test_workflow_command_and_keyword_matching() -> None:
    assert _matches({"triggerType": "command", "triggerValue": "/courses"}, "/COURSES")
    assert _matches({"triggerType": "contains", "triggerValue": "refund status"}, "What is my refund status?")
    assert not _matches({"triggerType": "command", "triggerValue": "/courses"}, "/courses now")


def test_workflow_renders_buttons_and_tables() -> None:
    buttons = _render({"id": "menu", "messageFormat": "buttons", "message": "Choose", "buttons": [{"id": "cma", "title": "CMA"}]})
    assert buttons.message_format["buttons"][0]["title"] == "CMA"
    table = _render({"id": "status", "messageFormat": "table", "message": "Access", "table": {"columns": ["Course", "Status"], "rows": [["CMA", "Active"]]}})
    assert "Course | Status" in table.content
    assert table.message_format["body"] == "Access"


def test_button_workflow_enforces_whatsapp_limits() -> None:
    with pytest.raises(ValidationError, match="1024"):
        BotWorkflowStep(id="long", name="Long", triggerType="command", triggerValue="/long", messageFormat="buttons", message="x" * 1025, buttons=[{"id": "ok", "title": "OK"}])
