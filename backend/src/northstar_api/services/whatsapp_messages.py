"""WhatsApp message content settings, independent of website appearance."""

import re

from northstar_api.models import Agent


def format_whatsapp_reply(agent: Agent, message: str) -> str:
    # Convert common model Markdown to the markers WhatsApp actually accepts.
    body = re.sub(r"\*\*(.+?)\*\*", r"*\1*", message)
    body = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", body, flags=re.MULTILINE)
    body = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", r"\1: \2", body)
    body = re.sub(r"```[a-zA-Z][\w+-]*\n", "```\n", body)
    settings = (agent.appearance or {}).get("whatsapp") or {}
    template = settings.get("replyTemplate") or "{message}"
    # Only substitute placeholders in the template, never in model/user content.
    return re.sub(
        r"\{(message|bot_name)\}",
        lambda match: body if match.group(1) == "message" else agent.name,
        template,
    ).strip()
