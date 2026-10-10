"""Security and structural contract tests for the page builder document."""
import pytest
from pydantic import ValidationError

from northstar_api.services.website_builder_document import BuilderPageDocument


def page(nodes):
    return BuilderPageDocument.model_validate({"slug": "welcome", "title": "Welcome", "nodes": nodes})


def test_valid_page_has_versioned_document():
    doc = page([{"id": "hero", "kind": "section", "children": [
        {"id": "heading", "kind": "heading", "text": "Hello"},
        {"id": "cta", "kind": "button", "text": "Read more", "url": "/about"},
    ]}])
    assert doc.schema_version == 1
    assert doc.nodes[0].children[1].url == "/about"


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,a", "//evil.example", "http://insecure.example", "/\\evil.example", "https://name:password@example.com"])
def test_unsafe_urls_rejected(url):
    with pytest.raises(ValidationError):
        page([{"id": "hero", "kind": "section", "children": [
            {"id": "cta", "kind": "button", "text": "Visit", "url": url},
        ]}])


def test_duplicate_ids_rejected():
    with pytest.raises(ValidationError, match="unique"):
        page([{"id": "hero", "kind": "section", "children": [
            {"id": "same", "kind": "heading", "text": "A"},
            {"id": "same", "kind": "paragraph", "text": "B"},
        ]}])


def test_invalid_nested_text_node_rejected():
    with pytest.raises(ValidationError):
        page([{"id": "hero", "kind": "section", "children": [
            {"id": "heading", "kind": "heading", "text": "Hi", "children": [
                {"id": "child", "kind": "paragraph", "text": "Nested"},
            ]},
        ]}])


def test_document_is_immutable():
    doc = page([])
    with pytest.raises(ValidationError):
        doc.title = "Changed"


def test_unknown_properties_are_rejected():
    with pytest.raises(ValidationError):
        page([{"id": "hero", "kind": "section", "untrusted_html": "<script>alert(1)</script>"}])


def test_node_count_limit():
    nodes = [{"id": f"section-{i}", "kind": "section"} for i in range(501)]
    with pytest.raises(ValidationError, match="limits"):
        page(nodes)


def test_indexing_requires_an_approved_https_canonical_url():
    with pytest.raises(ValidationError):
        BuilderPageDocument.model_validate({
            "slug": "search-landing", "title": "Search page",
            "seo": {"indexable": True},
        })
    with pytest.raises(ValidationError):
        BuilderPageDocument.model_validate({
            "slug": "search-landing", "title": "Search page",
            "seo": {"indexable": True, "canonical_url": "http://unsecured.example"},
        })
    with pytest.raises(ValidationError):
        BuilderPageDocument.model_validate({
            "slug": "search-landing", "title": "Search page",
            "seo": {"indexable": True, "canonical_url": "https://example.org/page?secret=1"},
        })


def test_search_metadata_is_versioned_with_content_and_defaults_noindex():
    doc = BuilderPageDocument.model_validate({"slug": "home", "title": "Home"})
    assert not doc.seo.indexable
    assert doc.seo.canonical_url is None
    indexed = BuilderPageDocument.model_validate({
        "slug": "landing", "title": "Landing",
        "seo": {
            "description": "Helpful products and pricing.",
            "canonical_url": "https://example.org/landing",
            "indexable": True,
        },
    })
    assert indexed.model_dump(mode="json")["seo"]["canonical_url"] == "https://example.org/landing"


@pytest.mark.parametrize("unsafe", [
    "/" + chr(92) + "external.example",
    "/contact" + chr(10) + "header",
    "https://example.org/path" + chr(92) + "fragment",
    "https://example.org/#tracking",
])
def test_browser_ambiguous_urls_are_rejected(unsafe):
    with pytest.raises(ValidationError):
        page([{"id": "hero", "kind": "section", "children": [
            {"id": "cta", "kind": "button", "text": "More", "url": unsafe},
        ]}])


@pytest.mark.parametrize("url", [
    "/\\\\unsafe.example/path",
    "/folder/\\\\relative",
    "/path\\nother",
    "https://example.org/path\\tunsafe",
    "https://example.org:0/unused",
    "https://example.org/#fragment",
    "https://someone:password@example.org/",
])
def test_ambiguous_builder_link_urls_are_rejected(url):
    with pytest.raises(ValidationError):
        page([{"id": "content", "kind": "section", "children": [
            {"id": "outbound", "kind": "button", "text": "Open", "url": url},
        ]}])


def test_first_party_form_blocks_require_same_origin_bounded_published_paths():
    workspace = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    href = f"/api/v1/site-forms/public/{workspace}/contact"
    doc = page([{"id": "section", "kind": "section", "children": [
        {"id":"contactform", "kind":"form", "text":"Contact our team", "url":href},
    ]}])
    assert doc.nodes[0].children[0].url == href
    for unsafe in [
        "https://other.example/form",
        "/api/v1/site-forms/public/not-uuid/contact",
        "/api/v1/site-forms/public/" + workspace + "/contact?query=1",
        "//malicious.example",
        "javascript:alert(1)",
    ]:
        with pytest.raises(ValidationError):
            page([{"id": "section", "kind": "section", "children": [
                {"id":"form", "kind":"form", "text":"Contact", "url":unsafe},
            ]}])
    with pytest.raises(ValidationError):
        page([{"id":"section","kind":"section","children":[
            {"id":"form","kind":"form","text":"Contact","url":href,
             "children":[{"id":"unsafe","kind":"paragraph","text":"Wrong child"}]},
        ]}])


def test_builder_persists_allowed_appearance_tokens_without_changing_old_revisions():
    legacy = page([{"id": "hero", "kind": "section", "children": [
        {"id": "text", "kind": "paragraph", "text": "Original copy"},
    ]}])
    assert legacy.nodes[0].appearance is None
    assert legacy.nodes[0].children[0].appearance is None
    styled = page([{"id": "hero", "kind": "section",
        "appearance": {"alignment": "center", "spacing": "spacious", "tone": "accent"},
        "children": [
            {"id": "text", "kind": "paragraph", "text": "Original copy",
             "appearance": {"alignment": "end", "spacing": "compact", "tone": "muted"}},
        ],
    }])
    serialized = styled.model_dump(mode="json")
    assert serialized["nodes"][0]["appearance"] == {
        "alignment": "center", "spacing": "spacious", "tone": "accent",
    }
    assert serialized["nodes"][0]["children"][0]["appearance"]["alignment"] == "end"
    assert page(serialized["nodes"]).nodes[0].appearance == styled.nodes[0].appearance


@pytest.mark.parametrize("unsafe", [
    {"alignment": "justify", "spacing": "normal", "tone": "accent"},
    {"alignment": "start", "spacing": "100vh", "tone": "accent"},
    {"alignment": "center", "spacing": "compact", "tone": "url(javascript:alert(1))"},
    {"alignment": "start", "spacing": "normal", "tone": "default", "css": "display:none"},
    {"alignment": "start", "spacing": "normal", "tone": "default", "onmouseover": "evil()"},
])
def test_node_appearance_rejects_unsafe_values_and_unknown_style_properties(unsafe):
    with pytest.raises(ValidationError):
        page([{"id": "hero", "kind": "section", "children": [
            {"id": "heading", "kind": "heading", "text": "Important",
             "appearance": unsafe},
        ]}])
