"""Safe deep duplication of CMS pages without reused block IDs or SEO identity."""
from __future__ import annotations

from uuid import uuid4

from northstar_api.services.website_builder_document import BuilderNode, BuilderPageDocument, PageSEO


def _copy_node(node: BuilderNode) -> BuilderNode:
    return node.model_copy(
        update={"id": uuid4().hex, "children": tuple(_copy_node(child) for child in node.children)},
        deep=True,
    )


def duplicate_page_document(
    source: BuilderPageDocument, *, new_slug: str, new_title: str,
) -> BuilderPageDocument:
    """Copy textual content/assets but create new identity and private search settings."""
    if not isinstance(source, BuilderPageDocument):
        raise TypeError("Source must be a validated page")
    return BuilderPageDocument.model_validate({
        "schema_version": source.schema_version,
        "slug": new_slug,
        "title": new_title,
        "nodes": [_copy_node(node).model_dump(mode="json") for node in source.nodes],
        "seo": PageSEO(
            description=source.seo.description,
            canonical_url=None,
            indexable=False,
        ).model_dump(mode="json"),
    })
