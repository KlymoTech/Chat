"""Atomic source-based reviews, full correction history and two-person acceptance."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from northstar_api.services.extraction_evidence import VALIDATOR_VERSION, leaf_blocks
from northstar_api.services.extraction_schema import Reading, digest
from northstar_api.services.extraction_validation import critical_page, review_digest, table_errors


def apply_review(record: dict[str, Any], reviewed_pages: list[dict[str, Any]],
                 resolutions: list[dict[str, Any]], reviewer: str) -> None:
    """Commit in-memory changes only after the entire submission validates.

    The existing HTTP endpoint versions and stores the successful package under
    its source row lock. Preserve its captured page-list reference on commit.
    """
    if record.get("schema_version") != 2:
        raise ValueError("Retry extraction to create the current evidence schema")
    if not reviewer or not reviewer.strip():
        raise ValueError("An authenticated reviewer identity is required")
    candidate = deepcopy(record)
    _apply(candidate, reviewed_pages, resolutions, reviewer)
    page_list = record["pages"]
    page_list[:] = candidate["pages"]
    candidate["pages"] = page_list
    record.clear()
    record.update(candidate)


def _apply(record: dict[str, Any], reviewed_pages: list[dict[str, Any]],
           resolutions: list[dict[str, Any]], reviewer: str) -> None:
    pages = record["pages"]
    if [p.get("number") for p in reviewed_pages] != [p["number"] for p in pages]:
        raise ValueError("Every source unit must be reviewed once, in order")
    issues = {issue["id"]: issue for issue in record["issues"]}
    if len(issues) != len(record["issues"]) or len({r.get("id") for r in resolutions}) != len(resolutions):
        raise ValueError("Duplicate issue identities or decisions")
    now = datetime.now(UTC).isoformat()
    history = record.setdefault("correction_history", [])
    source_sha = record["source_sha256"]
    invalidated: set[int] = set()
    for resolution in resolutions:
        if resolution.get("id") not in issues:
            raise ValueError("Unknown issue decision")
        if resolution.get("action") not in {"source_verified", "source_anomaly", "unresolved"}:
            raise ValueError("Unknown issue disposition")
        issue = issues[resolution["id"]]
        if issue.get("technical") and resolution["action"] != "unresolved":
            raise ValueError("Technical extraction failures require reprocessing, not reviewer approval")
        if not resolution.get("reason", "").strip():
            raise ValueError("Issue decisions require a source-based reason")
        before = deepcopy(issue)
        status = "open" if resolution["action"] == "unresolved" else "resolved"
        # Resubmitting an identical disposition during second review must not
        # clear the first signature. Changing its justification is a real edit.
        changed = (issue.get("status"), issue.get("disposition"), issue.get("resolution_reason")) != (
            status, resolution["action"], resolution["reason"])
        if not changed:
            continue
        issue.update(status=status, disposition=resolution["action"], resolution_reason=resolution["reason"],
                     resolved_by=reviewer, resolved_at=now)
        affected = [p["number"] for p in pages if issue["page"] in {0, p["number"]}]
        invalidated.update(affected)
        history.append({"kind": "issue", "id": issue["id"], "before": before, "after": deepcopy(issue),
                        "reviewer": reviewer, "reviewed_at": now, "source_sha256": source_sha,
                        "base_extraction_revision": record.get("extraction_revision")})
    all_ids = {b["id"] for p in pages for b in p.get("blocks", [])}
    logical_ids = {b["id"] for b in record.get("word", {}).get("blocks", [])}
    snapshots: dict[int, dict[str, Any]] = {}
    reasons: dict[int, str] = {}
    for page, submitted in zip(pages, reviewed_pages, strict=True):
        if not submitted.get("reason", "").strip() or submitted.get("structure_confirmed") is not True:
            raise ValueError("Confirm source coverage, order, structure and relationships for every unit")
        number = page["number"]
        before = review_digest(page)
        snapshots[number] = {k: deepcopy(v) for k, v in page.items() if k not in {"primary_review", "second_review"}}
        leaves = leaf_blocks(page)
        edits = submitted.get("blocks", [])
        edit_ids = [b.get("id") for b in edits]
        if len(edit_ids) != len(set(edit_ids)) or set(edit_ids) != {b["id"] for b in leaves}:
            raise ValueError("Review every leaf region exactly once; do not omit or duplicate regions")
        by_id = {b["id"]: b for b in leaves}
        leaves = [by_id[identity] for identity in edit_ids]
        page["blocks"] = [b for b in page.get("blocks", []) if b.get("status") == "split"] + leaves
        for order, (block, edit) in enumerate(zip(leaves, edits, strict=True)):
            block["reading_order"] = order
            if block.get("visual") is None or block.get("status") == "failed":
                raise ValueError("A region has no successful visual reading; reprocess it")
            structure = Reading.model_validate(edit.get("structure") or block.get("reviewed_structure") or block["visual"]).model_dump(mode="json")
            if any(identity not in logical_ids for identity in structure["source_logical_ids"]):
                raise ValueError("Unknown Word logical source mapping")
            if structure["text"] != edit.get("selected_text"):
                raise ValueError("Region text must match the reviewed structured text")
            if not structure["complete"] or structure["uncertain"] or "[[UNREADABLE]]" in structure["text"]:
                raise ValueError("Incomplete or unreadable source cannot be marked reviewed")
            if structure["kind"] == "table" and table_errors(structure["cells"]):
                raise ValueError("Table structure is unresolved: " + "; ".join(table_errors(structure["cells"])[:5]))
            links = edit.get("related_block_ids", [])
            if len(links) != len(set(links)) or any(link not in all_ids or link == block["id"] for link in links):
                raise ValueError("Region relationship references unknown, identical or duplicate blocks")
            if (structure["continues_from_previous"] or structure["continues_on_next"]) and not links:
                raise ValueError("Continued content requires explicit source-fragment relationships")
            block.update(selected_text=edit["selected_text"], reviewed_structure=structure,
                         related_block_ids=links, structure_reviewed=True, type=structure["kind"])
        text = submitted.get("selected_text")
        if not isinstance(text, str):
            raise ValueError("Reviewed source text must be a string")
        if leaves and "\n".join(b["selected_text"] for b in leaves) != text:
            raise ValueError("Page text must be the exact ordered projection of reviewed regions")
        if not leaves and page.get("source_unit") == "bytes" and text != page["native_text"]:
            raise ValueError("Text-file source bytes are authoritative; preserve source mistakes")
        if "[[UNREADABLE]]" in text or (not text and not submitted.get("blank_confirmed") and not leaves):
            raise ValueError("Confirm a blank source explicitly; unreadable content cannot be verified")
        if not leaves and page.get("requires_image") and text:
            raise ValueError("A blank visual inventory cannot contain invented source text")
        if not leaves and page.get("requires_image") and not page.get("inventory_complete"):
            raise ValueError("The source visual inventory is incomplete; reprocess it")
        page["selected_text"] = text
        # Explicit blank acceptance belongs to evidence and is fingerprinted.
        page["blank_confirmed"] = bool(submitted.get("blank_confirmed"))
        if before != review_digest(page):
            invalidated.add(number)
        reasons[number] = submitted["reason"]
    for logical in record.get("word", {}).get("blocks", []):
        mapped = sorted({p["number"] for p in pages for b in leaf_blocks(p)
                         if logical["id"] in (b.get("reviewed_structure") or {}).get("source_logical_ids", [])})
        if mapped or logical.get("mapping_status") == "source_reviewed":
            logical["rendered_pages"] = mapped
            logical["mapping_status"] = "source_reviewed" if mapped else "ambiguous"
    # A changed source fragment invalidates signatures on linked pages too.
    changed_ids = {b["id"] for p in pages if p["number"] in invalidated for b in p.get("blocks", [])}
    invalidated.update(p["number"] for p in pages for b in p.get("blocks", [])
                       if changed_ids.intersection(b.get("related_block_ids", [])))
    for page in pages:
        number = page["number"]
        if number in invalidated:
            page.pop("primary_review", None)
            page.pop("second_review", None)
        fingerprint = review_digest(page)
        review = {"reviewer": reviewer, "reviewed_at": now, "reason": reasons[number],
                  "content_sha256": fingerprint, "image_sha256": page.get("image_sha256"),
                  "source_sha256": source_sha, "config_sha256": record.get("config_sha256"),
                  "validator_version": VALIDATOR_VERSION, "structure_confirmed": True}
        primary = page.get("primary_review")
        if primary and primary.get("content_sha256") == fingerprint and primary.get("validator_version") == VALIDATOR_VERSION:
            if primary["reviewer"] != reviewer:
                page["second_review"] = review
        else:
            page["primary_review"] = review
            page.pop("second_review", None)
        page["requires_second_review"] = critical_page(page)
        after = {k: deepcopy(v) for k, v in page.items() if k not in {"primary_review", "second_review"}}
        history.append({"kind": "page", "page": number, "reviewer": reviewer, "reviewed_at": now,
                        "reason": reasons[number], "before": snapshots[number], "after": after,
                        "source_sha256": source_sha, "image_sha256": page.get("image_sha256"),
                        "selected_sha256": fingerprint, "base_extraction_revision": record.get("extraction_revision"),
                        "previous_event_sha256": digest(history[-1]) if history else None})
    record["approved_pages"] = [p["number"] for p in pages if p.get("primary_review")]
    record["review_status"] = "needs_review"
    record["review_sequence"] = record.get("review_sequence", 0) + 1
