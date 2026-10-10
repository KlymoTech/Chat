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


def test_noindex_until_owner_approves_search_metadata():
    assert '<meta name="robots" content="noindex, nofollow">' in render_page(build([]))


def test_approved_search_metadata_is_escaped_and_rendered():
    doc = BuilderPageDocument.model_validate({
        "slug": "products", "title": "Products",
        "seo": {
            "description": 'Great products & "clear" pricing',
            "canonical_url": "https://example.org/products",
            "indexable": True,
        },
    })
    html = render_page(doc)
    assert '<meta name="robots" content="index, follow">' in html
    assert '<meta name="description" content="Great products &amp; &quot;clear&quot; pricing">' in html
    assert '<link rel="canonical" href="https://example.org/products">' in html

def test_blog_page_renders_escaped_author_summary_and_locale():
    document = BuilderPageDocument.model_validate({
        "slug": "editorial", "title": "Our editorial",
        "content_type": "article",
        "blog": {
            "author": 'Author <script>alert(1)</script>',
            "category": 'Research & guides',
            "summary": 'Visible summary & reliable evidence',
            "locale": "en-IN",
        },
        "nodes": [],
    })
    html = render_page(document)
    assert '<html lang="en-IN">' in html
    assert 'By Author &lt;script&gt;alert(1)&lt;/script&gt;' in html
    assert '<script>alert(1)</script>' not in html
    assert 'Research &amp; guides' in html
    assert 'Visible summary &amp; reliable evidence' in html
    assert '<meta name="description" content="Visible summary &amp; reliable evidence">' in html
    assert '<meta name="robots" content="noindex, nofollow">' in html


def test_primary_navigation_uses_safe_markup_and_meaningful_landmark():
    page = build([], title="Customer support")
    html = render_page(page, navigation=(
        ('About & <company>', '/api/v1/site-cms/public/workspace/about'),
        ('Talk to us', '/api/v1/site-cms/public/workspace/contact'),
    ))
    assert '<nav class="site-nav" aria-label="Primary navigation">' in html
    assert 'About &amp; &lt;company&gt;' in html
    assert '<company>' not in html
    assert 'href="/api/v1/site-cms/public/workspace/contact"' in html
    assert 'href="#site-main"' in html
    assert '<script>' not in html


def test_no_published_navigation_does_not_create_empty_landmark():
    page = build([])
    assert 'aria-label="Primary navigation"' not in render_page(page)


def test_public_form_blocks_render_restricted_same_origin_iframe():
    from northstar_api.services.website_builder_document import BuilderPageDocument
    workspace = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    page = BuilderPageDocument.model_validate({
        "slug":"contact","title":"Get in touch",
        "nodes":[{"id":"top","kind":"section","children":[
            {"id":"contact","kind":"form","text":"Enquiry & assistance",
             "url":f"/api/v1/site-forms/public/{workspace}/contact"},
        ]}],
    })
    rendered = render_page(page)
    assert 'sandbox="allow-forms allow-same-origin"' in rendered
    assert 'referrerpolicy="no-referrer"' in rendered
    assert 'title="Enquiry &amp; assistance"' in rendered
    assert f'src="/api/v1/site-forms/public/{workspace}/contact"' in rendered
    assert "<script>Enquiry" not in rendered
