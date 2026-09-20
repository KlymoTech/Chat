from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from northstar_api.bot_workflow_schemas import BotWorkflowSave, BotWorkflowStep
from northstar_api.services.bot_workflows import _allowed_by_frequency, _matches, _render, _waiting_reply


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


def test_calendar_day_and_rolling_24_hour_rules_are_distinct() -> None:
    now = datetime(2026, 9, 20, 0, 15, tzinfo=UTC)
    sent = [SimpleNamespace(created_at=now - timedelta(minutes=30), content_json={"workflowStepId": "welcome"})]
    daily = {"id": "welcome", "repeatPolicy": "once_per_calendar_day", "calendarTimezone": "UTC"}
    rolling = {"id": "welcome", "repeatPolicy": "once_per_24_hours"}
    assert _allowed_by_frequency(daily, sent, now)
    assert not _allowed_by_frequency(rolling, sent, now)


def test_waiting_bot_repeats_only_configured_number_of_times() -> None:
    step = {"id": "menu", "botBehavior": "wait_for_next_trigger", "waitRepeatCount": 1, "waitingMessage": "Choose an option"}
    assert _waiting_reply(step, []).content == "Choose an option"
    sent = [SimpleNamespace(content_json={"workflowWaitingFor": "menu"})]
    assert _waiting_reply(step, sent) is None


def test_active_workflow_rejects_a_connection_to_a_missing_node() -> None:
    with pytest.raises(ValidationError, match="next step"):
        BotWorkflowSave(name="Connected flow", purpose="support", status="active", steps=[
            BotWorkflowStep(id="welcome", name="Welcome", triggerType="command", triggerValue="/start", message="Hi", nextStepId="missing")
        ])
