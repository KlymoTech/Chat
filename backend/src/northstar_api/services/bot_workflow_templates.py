"""Backend-owned workflow presets that can be persisted onto an Agent."""

from __future__ import annotations

from northstar_api.bot_workflow_schemas import BotWorkflowSave, BotWorkflowStep

ENROLLED_STUDENT_TUTOR = "enrolled_student_tutor"


def _step(**values) -> BotWorkflowStep:
    defaults = {
        "buttons": [], "table": None, "template": None, "config": {}, "condition": None,
        "true_step_id": None, "false_step_id": None, "next_step_id": None,
        "position_x": 40, "position_y": 40, "bot_behavior": "complete",
        "waiting_message": "Please choose an option or send the next command.",
        "wait_repeat_count": 0, "repeat_policy": "every_match", "max_sends": None,
        "cooldown_minutes": 0, "calendar_timezone": "Asia/Kolkata", "enabled": True,
    }
    defaults.update(values)
    return BotWorkflowStep(**defaults)


def enrolled_student_tutor() -> BotWorkflowSave:
    """Return the canonical enrollment-aware Education journey."""
    return BotWorkflowSave(
        name="Enrolled student learning journey",
        purpose="education",
        status="draft",
        steps=[
            _step(
                id="edu_greeting_course_menu",
                name="Greeting — course menu",
                trigger_type="command",
                trigger_value="hi",
                message_format="text",
                message=(
                    "📚 *Choose your active course*\n\n{{courses}}\n\n"
                    "Reply with the number for the course you want to study.\n"
                    "Send *Hi* or *courses* anytime to see this menu again."
                ),
                config={"systemAction": "education_course_menu"},
                position_x=36,
                position_y=54,
                bot_behavior="wait_for_next_trigger",
                waiting_message="Reply with the course number or course name.",
                wait_repeat_count=2,
            ),
            _step(
                id="edu_daily_welcome",
                name="Daily welcome (first message)",
                trigger_type="fallback",
                trigger_value="",
                message_format="text",
                message=(
                    "👋 *Welcome back to your learning assistant!*\n\n"
                    "I’ll continue with your active course. Send *courses* at any time to view or "
                    "switch your enrolled course."
                ),
                config={"systemAction": "education_daily_welcome", "continueOriginalMessage": True},
                repeat_policy="once_per_calendar_day",
                position_x=36,
                position_y=54,
            ),
            _step(
                id="edu_enrollment_route",
                name="Route by active enrollments",
                trigger_type="command",
                trigger_value="courses",
                message_format="text",
                message=(
                    "📚 *Choose your active course*\n\n{{courses}}\n\n"
                    "Reply with the number for the course you want to study.\n"
                    "Send *Hi* or *courses* anytime to see this menu again."
                ),
                config={
                    "systemAction": "education_course_menu",
                    "dynamicSource": "verified_active_enrollments",
                },
                next_step_id="edu_course_session",
                position_x=330,
                position_y=54,
                bot_behavior="wait_for_next_trigger",
                waiting_message="Reply with the course number or course name.",
                wait_repeat_count=2,
            ),
            _step(
                id="edu_course_session",
                name="Continue selected course",
                trigger_type="contains",
                trigger_value="study",
                message_format="text",
                message=(
                    "✅ Your course is selected. Ask any question from this course and I’ll answer "
                    "using its trained material."
                ),
                config={"systemAction": "education_continue_active_course", "persistUntil": "switch_course"},
                position_x=624,
                position_y=54,
            ),
            _step(
                id="edu_switch_course",
                name="Switch course",
                trigger_type="command",
                trigger_value="switch course",
                message_format="text",
                message="{{courses}}\n\nReply with a number or course name.",
                config={
                    "systemAction": "education_course_menu",
                    "dynamicSource": "verified_active_enrollments",
                },
                next_step_id="edu_course_session",
                position_x=330,
                position_y=220,
                bot_behavior="wait_for_next_trigger",
                waiting_message="Reply with the course number or course name.",
                wait_repeat_count=2,
            ),
            _step(
                id="edu_help",
                name="How to use the tutor",
                trigger_type="command",
                trigger_value="help",
                message_format="buttons",
                message=(
                    "Ask any course question normally. If you are enrolled in more than one course, "
                    "send *courses* or *switch course* whenever you want to change subjects."
                ),
                buttons=[
                    {"id": "courses", "title": "My courses"},
                    {"id": "switch_course", "title": "Switch course"},
                ],
                position_x=624,
                position_y=220,
            ),
            _step(id="edu_paper_menu", name="Choose paper", trigger_type="event", trigger_value="",
                message_format="text", message="Studying {{course}}. Choose a paper:\n{{papers}}",
                config={"systemAction": "education_paper_menu"}, position_x=36, position_y=390),
            _step(id="edu_selection_confirmed", name="Selection confirmed", trigger_type="event", trigger_value="",
                message_format="text", message="Selected: {{course}} / {{paper}}. Ask your question.",
                config={"systemAction": "education_selection_confirmed"}, position_x=330, position_y=390),
            _step(id="edu_missing_access", name="Course access missing", trigger_type="event", trigger_value="",
                message_format="text", message="{{course}} is selected. Your institute must configure curriculum and paper access before tutoring can begin.",
                config={"systemAction": "education_missing_access"}, position_x=624, position_y=390),
            _step(id="edu_access_denied", name="No verified enrollment", trigger_type="event", trigger_value="",
                message_format="text", message="Your course access is not active for this WhatsApp number. Please contact your institute to verify your number and enrollment.",
                config={"systemAction": "education_access_denied"}, position_x=915, position_y=390),
            _step(id="edu_missing_material", name="No approved course answer", trigger_type="event", trigger_value="",
                message_format="text", message="I don’t have enough verified information to answer that. Please check your course selection or contact your teacher.",
                config={"systemAction": "education_missing_material"}, position_x=36, position_y=560),
            _step(id="edu_web_label", name="External web answer label", trigger_type="event", trigger_value="",
                message_format="text", message="{{course}}: external web information, not verified against your published course material.",
                config={"systemAction": "education_web_label"}, position_x=330, position_y=560),
            _step(id="edu_review_notice", name="Teacher review notice", trigger_type="event", trigger_value="",
                message_format="text", message="This question has been sent for teacher review.",
                config={"systemAction": "education_review_notice"}, position_x=624, position_y=560),
            _step(id="edu_retry", name="Temporary retry", trigger_type="event", trigger_value="",
                message_format="text", message="I could not safely complete that answer right now. Please try again shortly.",
                config={"systemAction": "education_retry"}, position_x=36, position_y=730),
        ],
    )


def template(template_key: str) -> BotWorkflowSave | None:
    if template_key == ENROLLED_STUDENT_TUTOR:
        return enrolled_student_tutor()
    return None


def template_catalog() -> list[dict[str, object]]:
    workflow = enrolled_student_tutor()
    return [{
        "key": ENROLLED_STUDENT_TUTOR,
        "name": "Enrolled Student Tutor",
        "purpose": "education",
        "description": (
            "Daily welcome, enrollment-aware course routing, remembered study context and secure course switching."
        ),
        "workflow": workflow.model_dump(mode="json", by_alias=True),
    }]
