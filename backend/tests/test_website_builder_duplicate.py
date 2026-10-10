"""Copying builder pages must never reuse node IDs or SEO publication identity."""
import pytest
from pydantic import ValidationError

from northstar_api.services.website_builder_document import BuilderPageDocument
from northstar_api.services.website_builder_duplicate import duplicate_page_document


def test_deep_duplicate_new_block_identity_and_noindex():
    original = BuilderPageDocument.model_validate({
        "schema_version": 1,
        "slug": "existing-page",
        "title": "Existing",
        "seo": {"description": "A copied description", "canonical_url": "https://example.org/existing-page", "indexable": True},
        "nodes": [{"id": "section-a", "kind": "section", "children": [
            {"id": "heading-a", "kind": "heading", "text": "Visible content"},
            {"id": "image-a", "kind": "image", "url": "https://example.org/photo.png", "text": "Licensed photo"},
            {"id": "nested-a", "kind": "container", "children": [
                {"id": "paragraph-a", "kind": "paragraph", "text": "Detailed description"},
            ]},
        ]}],
    })
    duplicated = duplicate_page_document(original, new_slug="copied-page", new_title="Copied")
    assert duplicated.slug == "copied-page"
    assert duplicated.title == "Copied"
    assert duplicated.seo.description == original.seo.description
    assert duplicated.seo.canonical_url is None
    assert duplicated.seo.indexable is False
    old_ids = {original.nodes[0].id, *(node.id for node in original.nodes[0].children)}
    new_ids = {duplicated.nodes[0].id, *(node.id for node in duplicated.nodes[0].children)}
    assert old_ids.isdisjoint(new_ids)
    assert original.nodes[0].children[2].children[0].id != duplicated.nodes[0].children[2].children[0].id
    assert duplicated.nodes[0].children[1].url == "https://example.org/photo.png"
    assert original.seo.indexable is True
    assert original.slug == "existing-page"


def test_duplicate_checks_new_slug_and_keeps_page_limits():
    source = BuilderPageDocument.model_validate({"slug": "original", "title": "Original"})
    with pytest.raises(ValidationError):
        duplicate_page_document(source, new_slug="../unsafe", new_title="Copy")
    with pytest.raises(ValidationError):
        duplicate_page_document(source, new_slug="copy", new_title="")
    with pytest.raises(TypeError):
        duplicate_page_document({"slug": "original"}, new_slug="copy", new_title="Copy")
