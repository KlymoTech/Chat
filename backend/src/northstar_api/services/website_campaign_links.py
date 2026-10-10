"""Safe marketing campaign URL attribution without CRM integration.

Campaign links are first-party assets managed by the owner CMS. This module
accepts approved landing destinations, validates UTM fields, and does not send
visitor information to any provider.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

_UTM_VALUE = re.compile(r"^[\w .:/@+-]{1,120}$", re.UNICODE)


class CampaignLink(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    destination: str = Field(min_length=1, max_length=2048)
    source: str = Field(min_length=1, max_length=120)
    medium: str = Field(min_length=1, max_length=120)
    campaign: str = Field(min_length=1, max_length=120)
    content: str | None = Field(default=None, max_length=120)
    term: str | None = Field(default=None, max_length=120)

    @field_validator("destination")
    @classmethod
    def validate_destination(cls, value: str) -> str:
        parts = urlsplit(value.strip())
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise ValueError("Campaign destinations must be absolute HTTPS URLs without credentials")
        if parts.fragment:
            raise ValueError("Campaign destinations must not contain fragments")
        return value.strip()

    @field_validator("source", "medium", "campaign", "content", "term")
    @classmethod
    def validate_dimension(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not _UTM_VALUE.fullmatch(value):
            raise ValueError("Invalid UTM dimension")
        return value


def build_campaign_url(link: CampaignLink) -> str:
    """Preserve ordinary query parameters and replace all existing UTM keys."""
    parts = urlsplit(link.destination)
    query = [
        (key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in {"utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"}
    ]
    query.extend([
        ("utm_source", link.source),
        ("utm_medium", link.medium),
        ("utm_campaign", link.campaign),
    ])
    if link.content:
        query.append(("utm_content", link.content))
    if link.term:
        query.append(("utm_term", link.term))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
