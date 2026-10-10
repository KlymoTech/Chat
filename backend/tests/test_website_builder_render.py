"""Builder HTML export regression tests."""
import pytest
from pydantic import ValidationError

from northstar_api.services.website_builder_document import BuilderPageDocument
from northstar_api.services.website_builder_render import render_page, style_csp_hash


def build(nodes, title="Site"):
    return BuilderPageDocument.model_validate({"slug": "home", "title": title, "nodes": nodes})


def test_export_escapes_html_and_attributes():
    page = build([{"id": "hero", "kind": "section", "children": [
        {"id": "headline", "kind": "heading", "text": '<script>alert("x")</script>'},
        {"id": "image", "kind": "image", "text": '" onerror="alert(1)', "url": "https://example.org/a?q=1&b=2"},
    ]}], title="<unsafe>")
    html = render_page(page)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<title>&lt;unsafe&gt;</title>" in html
    assert 'alt="&quot; onerror=&quot;alert(1)"' in html
    assert "src=\"https://example.org/a?q=1&amp;b=2\"" in html


def test_export_links_are_safe_and_accessible():
    page = build([{"id": "hero", "kind": "section", "children": [
        {"id": "internal", "kind": "button", "text": "Internal", "url": "/about"},
        {"id": "external", "kind": "button", "text": "External", "url": "https://example.org"},
    ]}])
    html = render_page(page)
    assert 'href="/about"' in html
    assert 'href="https://example.org" rel="noopener noreferrer"' in html
    assert '<main id="site-main"><section' in html


def test_no_raw_markup_or_javascript_urls():
    with pytest.raises(ValidationError):
        build([{"id": "hero", "kind": "section", "children": [
            {"id": "unsafe", "kind": "button", "text": "Click", "url": "javascript:alert(1)"},
        ]])


def test_static_styles_are_hashable_for_strict_csp():
    doc = build([])
    html = render_page(doc)
    assert "<style>" in html
    assert 'href="#site-main"' in html
    assert style_csp_hash().startswith("sha256-")


def test_renderer_rejects_unvalidated_input():
    with pytest.raises(TypeError):
        render_page({"title": "unvalidated"})


def test_nested_layout_renders():
    page = build([{"id": "hero", "kind": "section", "children": [
        {"id": "container", "kind": "container", "children": [
            {"id": "body", "kind": "paragraph", "text": "Hello & welcome"},
        ]},
    ]}])
    html = render_page(page)
    assert '<div data-builder-id="container"><p data-builder-id="body">Hello &amp; welcome</p></div>' in html
