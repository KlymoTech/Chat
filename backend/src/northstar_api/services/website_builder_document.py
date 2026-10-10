"""Validated, framework-agnostic page document contract for the visual builder.

This module intentionally has no database or API side effects. Persisted revisions
and publishing endpoints can use the same validation contract in later increments.
"""
from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NodeKind = Literal["section", "container", "heading", "paragraph", "image", "button", "form"]
_ALLOWED_CHILDREN = {
    "section": {"container", "heading", "paragraph", "image", "button", "form"},
    "container": {"container", "heading", "paragraph", "image", "button", "form"},
    "heading": set(),
    "paragraph": set(),
    "image": set(),
    "button": set(),
    "form": set(),
}
_MAX_DEPTH = 12
_MAX_NODES = 500


def _safe_url(value: str) -> str:
    """Accept safe same-origin paths or explicit HTTPS destinations only."""
    if not isinstance(value, str):
        raise TypeError("URL must be text")
    value = value.strip()
    if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("URL cannot be empty or contain control characters")
    # Browser URL normalization can treat backslashes as URL authority separators.
    if "\\" in value:
        raise ValueError("Backslashes are not allowed in URLs")
    parts = urlsplit(value)
    if value.startswith("/") and not value.startswith("//"):
        if parts.scheme or parts.netloc:
            raise ValueError("Relative paths cannot specify an authority")
        return value
    if (
        parts.scheme == "https"
        and parts.hostname
        and parts.port != 0
        and not parts.username
        and not parts.password
        and not parts.fragment
    ):
        return value
    raise ValueError("Only same-origin paths or HTTPS URLs without credentials are allowed")


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
        if self.kind in {"image", "button", "form"} and not self.url:
            raise ValueError("Image/button URL is required")
        if self.kind in {"button", "form"} and not self.text:
            raise ValueError("Button label is required")
        if self.kind == "form" and not re.fullmatch(
            r"/api/v1/site-forms/public/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/[a-z0-9]+(?:-[a-z0-9]+)*",
            self.url or "",
        ):
            raise ValueError("Embedded forms must use first-party published form URLs")
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


class BlogMetadata(BaseModel):
    """Public editorial information; private drafts cannot enter the article index."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    author: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=240)
    reviewer: str | None = Field(default=None, max_length=120)
    locale: str = Field(default="en", pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")


class BuilderPageDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    slug: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    title: str = Field(min_length=1, max_length=180)
    nodes: tuple[BuilderNode, ...] = ()
    seo: PageSEO = Field(default_factory=PageSEO)
    content_type: Literal["page", "article"] = "page"
    blog: BlogMetadata | None = None

    @model_validator(mode="after")
    def check_tree(self) -> "BuilderPageDocument":
        if self.content_type == "article" and self.blog is None:
            raise ValueError("Articles require author, category, and summary")
        if self.content_type == "page" and self.blog is not None:
            raise ValueError("Blog metadata is only allowed for articles")
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
