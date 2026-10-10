"""Validated, framework-agnostic page document contract for the visual builder.

This module intentionally has no database or API side effects. Persisted revisions
and publishing endpoints can use the same validation contract in later increments.
"""
from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NodeKind = Literal["section", "container", "heading", "paragraph", "image", "button"]
_ALLOWED_CHILDREN = {
    "section": {"container", "heading", "paragraph", "image", "button"},
    "container": {"container", "heading", "paragraph", "image", "button"},
    "heading": set(),
    "paragraph": set(),
    "image": set(),
    "button": set(),
}
_MAX_DEPTH = 12
_MAX_NODES = 500


def _safe_url(value: str) -> str:
    """Reject ambiguous URLs before they are inserted into browser attributes."""
    value = value.strip()
    if not value:
        raise ValueError("URL must not be empty")
    if any(ord(char) < 32 or ord(char) == 127 or ord(char) == 92 for char in value):
        raise ValueError("URLs cannot contain control characters or backslashes")
    parts = urlsplit(value)
    if value.startswith("/") and not value.startswith("//") and not parts.netloc:
        return value
    if (
        parts.scheme == "https"
        and parts.hostname
        and not parts.username
        and not parts.password
        and not parts.fragment
    ):
        return value
    raise ValueError("Only local paths or HTTPS URLs without credentials are allowed")

class BuilderNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    kind: NodeKind
    text: str | None = Field(default=None, max_length=10000)
    url: str | None = None
    children: tuple["BuilderNode", ...] = ()

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        return _safe_url(value) if value is not None else None

    @model_validator(mode="after")
    def check_shape(self) -> "BuilderNode":
        if self.kind in {"heading", "paragraph"} and not self.text:
            raise ValueError("Text content is required")
        if self.kind in {"image", "button"} and not self.url:
            raise ValueError("Image/button URL is required")
        if self.kind == "button" and not self.text:
            raise ValueError("Button label is required")
        if self.kind in {"section", "container"} and (self.text is not None or self.url is not None):
            raise ValueError("Layout nodes cannot contain text or URLs")
        if any(child.kind not in _ALLOWED_CHILDREN[self.kind] for child in self.children):
            raise ValueError("Node cannot contain these children")
        return self


class PageSEO(BaseModel):
    """Owner-approved organic search metadata; pages are noindex until configured."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str = Field(default="", max_length=160)
    canonical_url: str | None = Field(default=None, max_length=2048)
    indexable: bool = False

    @field_validator("canonical_url")
    @classmethod
    def validate_canonical(cls, value: str | None) -> str | None:
        if value is None or value.strip() == "":
            return None
        value = value.strip()
        parts = urlsplit(value)
        if (
            parts.scheme != "https" or not parts.hostname
            or parts.username or parts.password
            or parts.fragment or parts.query
        ):
            raise ValueError("Canonical URLs must be HTTPS without credentials, query or fragment")
        return value

    @model_validator(mode="after")
    def require_canonical_before_indexing(self) -> "PageSEO":
        if self.indexable and not self.canonical_url:
            raise ValueError("An approved canonical URL is required before indexing")
        return self


class BuilderPageDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    slug: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    title: str = Field(min_length=1, max_length=180)
    nodes: tuple[BuilderNode, ...] = ()
    seo: PageSEO = Field(default_factory=PageSEO)

    @model_validator(mode="after")
    def check_tree(self) -> "BuilderPageDocument":
        ids: set[str] = set()
        count = 0
        stack = [(node, 1) for node in self.nodes]
        while stack:
            node, depth = stack.pop()
            count += 1
            if count > _MAX_NODES or depth > _MAX_DEPTH:
                raise ValueError("Page exceeds builder limits")
            if node.id in ids:
                raise ValueError("Node identifiers must be unique across a page")
            ids.add(node.id)
            if node.kind != "section" and depth == 1:
                raise ValueError("Page root nodes must be sections")
            stack.extend((child, depth + 1) for child in node.children)
        return self
