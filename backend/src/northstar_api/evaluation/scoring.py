"""Accuracy metrics for extracted pages against known ground truth.

All text metrics compare Unicode-normalized text with whitespace collapsed, because line
wrapping is layout, not content. Everything else (digits, signs, punctuation, case) counts.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def cer(truth: str, predicted: str) -> float:
    """Character error rate: edits needed per ground-truth character (0 is perfect)."""
    expected, actual = normalize(truth), normalize(predicted)
    if not expected:
        return 0.0 if not actual else 1.0
    return Levenshtein.distance(expected, actual) / len(expected)


def wer(truth: str, predicted: str) -> float:
    """Word error rate: word-level edits per ground-truth word (0 is perfect)."""
    expected, actual = normalize(truth).split(), normalize(predicted).split()
    if not expected:
        return 0.0 if not actual else 1.0
    return Levenshtein.distance(expected, actual) / len(expected)


def table_cell_accuracy(truth_rows: list[list[str]], cells: list[dict[str, Any]]) -> float:
    """Share of cells correct at the right row and column; missing or extra cells count as wrong."""
    predicted = {(c["row"], c["column"]): normalize(c.get("text") or "") for c in cells}
    expected = {(r, c): normalize(v) for r, row in enumerate(truth_rows) for c, v in enumerate(row)}
    keys = set(expected) | {k for k, v in predicted.items() if v}
    if not keys:
        return 1.0
    return sum(expected.get(k, "") == predicted.get(k, "") for k in keys) / len(keys)


def reading_order(truth_blocks: list[str], predicted_text: str) -> float:
    """Share of block pairs that appear in the correct relative order (missing blocks count as wrong)."""
    haystack = normalize(predicted_text)

    def locate(block: str) -> int:
        """Where the block starts; tolerant of reading errors so they are not counted as order errors."""
        needle = normalize(block)[:60]
        exact = haystack.find(needle)
        if exact >= 0 or not needle:
            return exact
        match = fuzz.partial_ratio_alignment(needle, haystack)
        return match.dest_start if match and match.score >= 80 else -1

    positions = [locate(block) for block in truth_blocks if normalize(block)]
    pairs = [(a, b) for i, a in enumerate(positions) for b in positions[i + 1 :]]
    if not pairs:
        return 1.0
    return sum(a >= 0 and b >= 0 and a < b for a, b in pairs) / len(pairs)


def _flatten(text: str) -> str:
    """Table rows are serialized as 'a | b | c'; the separators are structure, not content."""
    return text.replace(" | ", " ")


def _inside(inner: list[float], outer: list[float]) -> bool:
    cx, cy = (inner[0] + inner[2]) / 2, (inner[1] + inner[3]) / 2
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def region_text(block: dict[str, Any]) -> str | None:
    """What the pipeline offers for a region: its settled text, else its draft."""
    if block.get("selected_text") is not None:
        return str(block["selected_text"])
    for key in ("proposed_structure", "visual"):
        if block.get(key):
            return str(block[key].get("text") or "")
    return None


def score_page(truth: dict[str, Any], page: dict[str, Any]) -> dict[str, Any]:
    """Compare one extracted page with its ground truth.

    ``truth`` holds blocks in reading order, each with ``text``, ``bbox_pt`` and, for tables,
    ``rows``. Region boxes are matched by position, so a split region is still attributed to the
    ground-truth block it came from.
    """
    scale = page.get("render_scale") or 1
    leaves = [b for b in page.get("blocks", []) if b.get("status") != "split"]
    truth_blocks = truth["blocks"]
    # Text drawn inside images is scored separately: only OCR/vision can see it.
    text_blocks = [b for b in truth_blocks if b["kind"] != "figure"]
    image_blocks = [b for b in truth_blocks if b["kind"] == "figure"]
    truth_text = _flatten("\n".join(b["text"] for b in text_blocks))

    def is_image(block: dict[str, Any]) -> bool:
        box_pt = [v / scale for v in block.get("bbox_px") or [0, 0, 0, 0]]
        return any(_inside(box_pt, t["bbox_pt"]) for t in image_blocks) and not block.get("native_text")

    if leaves:
        predicted_text = _flatten("\n".join(t for t in (region_text(b) for b in leaves if not is_image(b)) if t))
        image_text = " ".join(t for t in (region_text(b) for b in leaves if is_image(b)) if t)
    else:
        predicted_text = _flatten(page.get("selected_text") or page.get("native_text") or "")
        image_text = ""

    false_accepts, settled = [], 0
    tables: list[float] = []
    for block in leaves:
        box_pt = [v / scale for v in block.get("bbox_px") or [0, 0, 0, 0]]
        owners = [t for t in truth_blocks if _inside(box_pt, t["bbox_pt"]) or _inside(t["bbox_pt"], box_pt)]
        if block.get("selected_text") is not None:
            settled += 1
            text = normalize(block["selected_text"].replace(" | ", " "))
            if text and not any(text in normalize(t["text"].replace(" | ", " ")) for t in owners):
                false_accepts.append({"block_id": block["id"], "text": block["selected_text"][:120]})
    for truth_block in truth_blocks:
        if "rows" not in truth_block:
            continue
        candidates = [b for b in leaves if b.get("bbox_px") and _inside(
            truth_block["bbox_pt"], [v / scale for v in b["bbox_px"]])]
        cells = next(((b.get("proposed_structure") or b.get("visual") or {}).get("cells") or
                      (b.get("native_table") or {}).get("cells") for b in candidates
                      if (b.get("native_table") or (b.get("proposed_structure") or {}).get("cells"))), None)
        tables.append(table_cell_accuracy(truth_block["rows"], cells or []))
    return {
        "cer": round(cer(truth_text, predicted_text), 5),
        "wer": round(wer(truth_text, predicted_text), 5),
        "reading_order": round(reading_order([_flatten(b["text"]) for b in text_blocks], predicted_text), 4),
        "image_text_wer": round(wer(" ".join(b["text"] for b in image_blocks), image_text), 4) if image_blocks else None,
        "table_cell_accuracy": round(sum(tables) / len(tables), 4) if tables else None,
        "regions": len(leaves),
        "settled_regions": settled,
        "false_accepts": false_accepts,
    }
