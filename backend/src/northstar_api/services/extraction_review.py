"""Atomic, versioned source decisions with independent critical-content review."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from northstar_api.services.extraction_schema import POLICY_VERSION, Reading, digest
from northstar_api.services.extraction_structure import assemble_logical, structure_errors
from northstar_api.services.extraction_validation import critical_page, current_review, review_context, review_digest


def _editable_page(page: dict[str, Any]) -> dict[str, Any]:
    return {"selected_text": page.get("selected_text"), "blank_confirmed": page.get("blank_confirmed", False),
            "blocks": [{key: block.get(key) for key in ("id", "type", "selected_text", "reviewed_structure", "related_block_ids")}
                       for block in page.get("blocks", [])]}


def apply_review(record: dict[str, Any], reviewed_pages: list[dict[str, Any]],
                 resolutions: list[dict[str, Any]], reviewer: str) -> None:
    """Prepare the complete transaction before changing the caller's record.

    A subset of pages can be saved. Release still requires every page and every
    critical second review. Keep the original page-list identity for API callers
    that captured it before this function (including the approval endpoint).
    """
    if record.get("schema_version") != 2:
        raise ValueError("Retry extraction to create the current evidence schema")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("A verified reviewer identity is required")
    numbers = [page.get("number") for page in reviewed_pages]
    known = {page["number"] for page in record["pages"]}
    if not numbers or any(type(n) is not int or n not in known for n in numbers) or numbers != sorted(set(numbers)):
        raise ValueError("Review known source units once each, in source order")
    if len({resolution.get("id") for resolution in resolutions}) != len(resolutions):
        raise ValueError("Duplicate issue decisions")

    draft = deepcopy(record)
    pages = draft["pages"]
    by_number = {page["number"]: page for page in pages}
    all_ids = {block["id"] for page in pages for block in page.get("blocks", []) if block.get("status") != "split"}
    word_blocks = {block["id"]: block for block in draft.get("word", {}).get("blocks", [])}
    all_ids.update(word_blocks)
    issues = {issue["id"]: issue for issue in draft.get("issues", [])}
    now = datetime.now(UTC).isoformat()
    history = draft.setdefault("correction_history", [])
    before = {page["number"]: _editable_page(page) for page in pages}
    before_hash = {page["number"]: review_digest(page) for page in pages}

    for resolution in resolutions:
        issue = issues.get(resolution.get("id"))
        action = resolution.get("action")
        reason = resolution.get("reason")
        if issue is None:
            raise ValueError("Unknown issue decision")
        if action not in {"source_verified", "source_anomaly", "unresolved"}:
            raise ValueError("Unknown issue disposition")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Issue decisions require a source-based reason")
        if issue.get("technical") and action != "unresolved":
            raise ValueError("Technical extraction failures require reprocessing, not reviewer approval")
        status = "open" if action == "unresolved" else "resolved"
        if (issue.get("status"), issue.get("disposition"), issue.get("resolution_reason")) == (status, action, reason):
            continue
        previous = dict(issue)
        issue.update({"status": status, "disposition": action, "resolution_reason": reason,
                      "resolved_by": reviewer, "resolved_at": now})
        history.append({"kind": "issue", "id": issue["id"], "before": previous, "after": dict(issue),
                        "reviewer": reviewer, "reviewed_at": now})

    for submitted in reviewed_pages:
        page = by_number[submitted["number"]]
        if not isinstance(submitted.get("reason"), str) or not submitted["reason"].strip() or submitted.get("structure_confirmed") is not True:
            raise ValueError("Confirm source coverage, order, structure and relationships for every reviewed unit")
        leaves = [block for block in page.get("blocks", []) if block.get("status") != "split"]
        edits = submitted.get("blocks", [])
        if [edit.get("id") for edit in edits] != [block["id"] for block in leaves]:
            raise ValueError("Review every leaf region in source reading order")
        for block, edit in zip(leaves, edits, strict=True):
            raw = edit.get("structure") if edit.get("structure") is not None else block.get("reviewed_structure") or block.get("visual")
            if raw is None or block.get("visual") is None:
                raise ValueError("A region has no successful visual reading; reprocess it")
            structure = Reading.model_validate(raw).model_dump()
            if not structure["complete"]:
                raise ValueError("Incomplete model or reviewer structures cannot be approved")
            if structure["text"] != edit.get("selected_text"):
                raise ValueError("Region text must match the reviewed structured text")
            references = edit.get("related_block_ids", [])
            if (not isinstance(references, list) or any(not isinstance(ref, str) for ref in references)
                    or len(references) != len(set(references))
                    or any(ref not in all_ids or ref == block["id"] for ref in references)):
                raise ValueError("Region relationship references an unknown, duplicate, split, or identical block")
            block.update({"type": structure["kind"], "selected_text": edit["selected_text"],
                          "reviewed_structure": structure, "related_block_ids": references, "structure_reviewed": True})
            errors = structure_errors(block)
            if errors:
                raise ValueError(f"{block['id']}: " + "; ".join(errors))
        text = submitted.get("selected_text")
        if not isinstance(text, str):
            raise ValueError("Selected source text must be a string")
        if leaves and "\n".join(block["selected_text"] for block in leaves) != text:
            raise ValueError("Page text must be the exact ordered projection of reviewed regions")
        if not leaves and page.get("source_unit") == "bytes" and text != page.get("native_text"):
            raise ValueError("Text-file source bytes are authoritative; source mistakes must be preserved")
        if "[[UNREADABLE]]" in text or (not text and not submitted.get("blank_confirmed") and not leaves):
            raise ValueError("Confirm a blank source explicitly; unreadable text is never verified")
        if page.get("requires_image") and not page.get("image"):
            raise ValueError("Source rendering is required before source review")
        page["selected_text"] = text
        page["blank_confirmed"] = submitted.get("blank_confirmed") is True
        page["requires_second_review"] = critical_page(page)

    # References to native Word IDs establish explicit, reviewable source-to-render mappings.
    for word_id, logical in word_blocks.items():
        matches = [(page, block) for page in pages for block in page.get("blocks", [])
                   if word_id in block.get("related_block_ids", []) and block.get("status") != "split"]
        if matches:
            new_ids = [block["id"] for _, block in matches]
            if new_ids != logical.get("mapping_evidence_block_ids"):
                logical.update({"rendered_pages": sorted({page["number"] for page, _ in matches}),
                                "mapping_status": "source_reviewed", "mapping_evidence_block_ids": new_ids,
                                "mapping_review_reason": "; ".join(item["reason"] for item in reviewed_pages)})
        elif logical.get("mapping_status") == "source_reviewed":
            logical.update({"rendered_pages": [], "mapping_status": "ambiguous", "mapping_evidence_block_ids": []})

    # Invalidate approvals on affected pages and linked source fragments before signing.
    for page in pages:
        page["review_context_sha256"] = review_context(draft, page["number"])
        for key in ("primary_review", "second_review"):
            if page.get(key) and not current_review(draft, page, page[key]):
                page.pop(key)
    for submitted in reviewed_pages:
        page = by_number[submitted["number"]]
        after = review_digest(page)
        review = {"reviewer": reviewer, "reviewed_at": now, "reason": submitted["reason"],
                  "content_sha256": after, "image_sha256": page.get("image_sha256"),
                  "source_sha256": draft["source_sha256"], "structure_confirmed": True,
                  "policy_version": POLICY_VERSION}
        primary = page.get("primary_review")
        if primary and primary["reviewer"] != reviewer:
            page["second_review"] = review
        else:
            page["primary_review"] = review
        history.append({"kind": "page", "page": page["number"], "reviewer": reviewer,
                        "reviewed_at": now, "reason": submitted["reason"],
                        "before": before[page["number"]], "after": _editable_page(page),
                        "previous_sha256": before_hash[page["number"]], "selected_sha256": after,
                        "image_sha256": page.get("image_sha256"), "structure_sha256": digest(submitted.get("blocks", []))})
    draft["approved_pages"] = [page["number"] for page in pages if current_review(draft, page, page.get("primary_review"))]
    draft["review_status"] = "needs_review"
    draft["review_revision"] = draft.get("review_revision", 0) + 1
    draft["validation_policy_version"] = POLICY_VERSION
    draft["logical_blocks"] = assemble_logical(draft)

    # No mutation has occurred until this point. Preserve aliases held by the API.
    original_pages = record["pages"]
    for original, changed in zip(original_pages, pages, strict=True):
        original.clear()
        original.update(changed)
    draft["pages"] = original_pages
    record.clear()
    record.update(draft)
