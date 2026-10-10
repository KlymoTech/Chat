"""Safe, responsive HTML export for versioned website builder pages.

No visitor-supplied scripts or styles can run. A SHA256 CSP hash allows only
the exact static stylesheet emitted by this renderer.
"""
from __future__ import annotations

import base64
import hashlib
from html import escape

from northstar_api.services.website_builder_document import BuilderNode, BuilderPageDocument

SITE_CSS = (
    "*,*::before,*::after{box-sizing:border-box}"
    "html{scroll-behavior:smooth}"
    "body{margin:0;background:#f8fafc;color:#172033;font:16px/1.7 system-ui,-apple-system,Segoe UI,sans-serif}"
    ".skip-link{position:absolute;left:-9999px;top:0;padding:12px;background:#fff;z-index:10}"
    ".skip-link:focus{left:12px}"
    "a:focus-visible{outline:3px solid #f59e0b;outline-offset:4px}"
    ".site-header{padding:clamp(28px,5vw,64px) 24px 18px;max-width:1100px;margin:auto}"
    ".site-header h1{font-size:clamp(2rem,5vw,3.6rem);line-height:1.14;letter-spacing:-.03em;margin:0}"
    ".site-eyebrow{color:#475569;font-size:.85rem;text-transform:uppercase;letter-spacing:.13em}"
    "main{max-width:1100px;margin:auto;padding:20px 24px 88px}"
    "main>section{padding:clamp(24px,4vw,48px);margin:24px 0;background:#fff;border:1px solid #e2e8f0;"
    "border-radius:22px;box-shadow:0 12px 32px rgba(15,23,42,.04)}"
    "h2{font-size:clamp(1.45rem,3vw,2.4rem);line-height:1.22;letter-spacing:-.02em}"
    "p{max-width:72ch} img{display:block;max-width:100%;height:auto;border-radius:12px}"
    "a.site-action{display:inline-flex;align-items:center;justify-content:center;background:#1d4ed8;"
    "border-radius:10px;color:#fff;font-weight:650;padding:12px 24px;text-decoration:none;margin:8px 0}"
    "a.site-action:hover{background:#1e40af}"
    ".site-footer{max-width:1100px;margin:auto;padding:22px 24px 64px;border-top:1px solid #cbd5e1;color:#475569}"
    ".site-footer a{color:#1d4ed8;font-weight:650}"
    ".site-byline{color:#334155;font-weight:600}.site-summary{max-width:65ch;color:#475569}"
    "@media(max-width:480px){main,.site-header{padding-left:14px;padding-right:14px}"
    "main>section{margin:14px 0;border-radius:15px}}"
    "@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}"
)


def style_csp_hash() -> str:
    digest = hashlib.sha256(SITE_CSS.encode("utf-8")).digest()
    return "sha256-" + base64.b64encode(digest).decode("ascii")


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
            f'<a class="site-action" data-builder-id="{_attr(node.id)}" href="{_attr(url)}"'
            f'{protection}>{escape(node.text or "")}</a>'
        )
    tag = "section" if node.kind == "section" else "div"
    children = "".join(_render_node(child) for child in node.children)
    return f'<{tag} data-builder-id="{_attr(node.id)}">{children}</{tag}>'


def render_page(
    document: BuilderPageDocument,
    *,
    privacy_path: str | None = None,
    analytics_context: tuple[str, str] | None = None,
    analytics_nonce: str | None = None,
) -> str:
    """Render only validated builder data, never arbitrary user-provided markup."""
    if not isinstance(document, BuilderPageDocument):
        raise TypeError("Expected validated BuilderPageDocument")
    sections = "".join(_render_node(node) for node in document.nodes)
    title = escape(document.title)
    robots = "index, follow" if document.seo.indexable else "noindex, nofollow"
    seo_metadata = '<meta name="robots" content="' + robots + '">'
    effective_description = document.seo.description or (
        document.blog.summary if document.blog is not None else ""
    )
    if effective_description:
        seo_metadata += (
            '<meta name="description" content="'
            + _attr(effective_description)
            + '">'
        )
    if document.seo.canonical_url:
        seo_metadata += (
            '<link rel="canonical" href="'
            + _attr(document.seo.canonical_url)
            + '">'
        )
    article_header = ""
    language = "en"
    if document.content_type == "article" and document.blog is not None:
        language = document.blog.locale
        article_header = (
            '<p class="site-byline">By ' + escape(document.blog.author)
            + ' · ' + escape(document.blog.category) + '</p>'
            + '<p class="site-summary">' + escape(document.blog.summary) + '</p>'
        )
    privacy_footer = (
        '<footer class="site-footer"><a href="' + _attr(privacy_path) +
        '">Privacy and tracking preferences</a></footer>'
        if privacy_path else ""
    )
    analytics_script = ""
    if analytics_context is not None and analytics_nonce is not None:
        workspace_id, api_prefix = analytics_context
        script_src = api_prefix.rstrip("/") + "/site-analytics/client.js"
        analytics_script = (
            '<script defer nonce="' + _attr(analytics_nonce) +
            '" src="' + _attr(script_src) +
            '" data-site-workspace="' + _attr(workspace_id) +
            '" data-site-slug="' + _attr(document.slug) +
            '" data-api-prefix="' + _attr(api_prefix) + '"></script>'
        )
    return (
        "<!doctype html>\n"
        f'<html lang="{_attr(language)}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{title}</title>{seo_metadata}<style>{SITE_CSS}</style>"
        "</head><body>"
        '<a class="skip-link" href="#site-main">Skip to content</a>'
        f'<header class="site-header"><p class="site-eyebrow">{"Article" if document.content_type == "article" else "Welcome"}</p><h1>{title}</h1>{article_header}</header>'
        f'<main id="site-main">{sections}</main>'
        f"{privacy_footer}"
        f"{analytics_script}"
        "</body></html>"
    )
