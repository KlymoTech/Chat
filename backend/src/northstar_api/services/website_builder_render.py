"""Safe, deterministic HTML export for versioned visual-builder documents.

Exports HTML without scripts, event handlers, inline styles or executable URLs.
A hosting/publishing layer must separately provide authentication, CSP and caching.
"""
from __future__ import annotations

from html import escape

from northstar_api.services.website_builder_document import BuilderNode, BuilderPageDocument


def _attr(value: str) -> str:
    return escape(value, quote=True)


def _render_node(node: BuilderNode) -> str:
    if node.kind == "heading":
        return f'<h2 data-builder-id="{_attr(node.id)}">{escape(node.text or "")}</h2>'
    if node.kind == "paragraph":
        return f'<p data-builder-id="{_attr(node.id)}">{escape(node.text or "")}</p>'
    if node.kind == "image":
        return (
            f'<img data-builder-id="{_attr(node.id)}" src="{_attr(node.url or "")}" '
            f'alt="{_attr(node.text or "")}" loading="lazy">'
        )
    if node.kind == "button":
        url = node.url or ""
        external = url.startswith("https://")
        protection = ' rel="noopener noreferrer"' if external else ""
        return (
            f'<a data-builder-id="{_attr(node.id)}" href="{_attr(url)}"'
            f'{protection}>{escape(node.text or "")}</a>'
        )
    tag = "section" if node.kind == "section" else "div"
    children = "".join(_render_node(child) for child in node.children)
    return f'<{tag} data-builder-id="{_attr(node.id)}">{children}</{tag}>'


def render_page(document: BuilderPageDocument) -> str:
    """Render only validated builder data, never arbitrary user-provided markup."""
    if not isinstance(document, BuilderPageDocument):
        raise TypeError("Expected validated BuilderPageDocument")
    sections = "".join(_render_node(node) for node in document.nodes)
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(document.title)}</title>"
        "</head><body>"
        f"<main>{sections}</main>"
        "</body></html>"
    )
