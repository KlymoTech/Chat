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
    value = value.strip()
    parts = urlsplit(value)
    if value.startswith("/") and not value.startswith("//") and not value.startswith("/\\"):
        return value
    if parts.scheme == "https" and parts.netloc and not parts.username and not parts.password:
        return value
    raise ValueError("Only relative paths or HTTPS URLs are allowed")


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


class BuilderPageDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    slug: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    title: str = Field(min_length=1, max_length=180)
    nodes: tuple[BuilderNode, ...] = ()

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
