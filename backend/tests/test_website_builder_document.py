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
