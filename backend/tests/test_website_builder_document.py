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
