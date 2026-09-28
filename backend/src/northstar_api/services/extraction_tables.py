"""Deterministic table structure from word positions.

Works with PDF text-layer words and OCR words alike. Rows come from word baselines, cells from
the wide gaps between words, and columns from the horizontal gaps that every data row shares —
so ruled, striped and whitespace-aligned tables are handled the same way, and the grid is
anchored to real word positions instead of a model's guess.
"""

from __future__ import annotations

from statistics import median
from typing import Any

Word = dict[str, Any]


def _height(words: list[Word]) -> float:
    return median(w["bbox_px"][3] - w["bbox_px"][1] for w in words) if words else 0.0


def _rows(words: list[Word], tolerance: float) -> list[list[Word]]:
    rows: list[list[Word]] = []
    centers: list[float] = []
    for word in sorted(words, key=lambda w: (w["bbox_px"][1] + w["bbox_px"][3]) / 2):
        center = (word["bbox_px"][1] + word["bbox_px"][3]) / 2
        if rows and abs(center - centers[-1]) <= tolerance:
            rows[-1].append(word)
            centers[-1] = sum((w["bbox_px"][1] + w["bbox_px"][3]) / 2 for w in rows[-1]) / len(rows[-1])
        else:
            rows.append([word])
            centers.append(center)
    return [sorted(row, key=lambda w: w["bbox_px"][0]) for row in rows]


def _chunks(row: list[Word], gap: float) -> list[dict[str, Any]]:
    """Words closer than ``gap`` belong to the same cell ("All crops", "Water (L/day)")."""
    chunks: list[dict[str, Any]] = []
    for word in row:
        box = word["bbox_px"]
        if chunks and box[0] - chunks[-1]["bbox_px"][2] <= gap:
            last = chunks[-1]
            last["words"].append(word)
            last["bbox_px"] = [min(last["bbox_px"][0], box[0]), min(last["bbox_px"][1], box[1]),
                               max(last["bbox_px"][2], box[2]), max(last["bbox_px"][3], box[3])]
        else:
            chunks.append({"words": [word], "bbox_px": list(box)})
    for chunk in chunks:
        chunk["text"] = " ".join(w["text"] for w in chunk["words"])
    return chunks


def _columns(intervals: list[tuple[float, float]], tolerance: float) -> list[list[float]]:
    columns: list[list[float]] = []
    for x0, x1 in sorted(intervals):
        if columns and x0 <= columns[-1][1] + tolerance:
            columns[-1][1] = max(columns[-1][1], x1)
        else:
            columns.append([x0, x1])
    return columns


def table_grid(words: list[Word]) -> dict[str, Any] | None:
    """A row/column grid for ``words``, or None when they do not form a table."""
    if len(words) < 6:
        return None
    height = _height(words)
    rows = [_chunks(row, gap=0.9 * height) for row in _rows(words, tolerance=0.5 * height)]
    if len(rows) < 3:
        return None
    data = rows[1:]  # a header may span columns; data rows define the column gaps
    columns = _columns([(c["bbox_px"][0], c["bbox_px"][2]) for row in data for c in row], tolerance=0.2 * height)
    if len(columns) < 2:
        return None
    left = min(w["bbox_px"][0] for w in words)
    right = max(w["bbox_px"][2] for w in words)
    chunks = [c for row in rows for c in row]
    if sum(len(row) >= 2 for row in rows) < 0.7 * len(rows):
        return None
    # Body text laid out in two columns also has two "cells" per line, but its cells are wide.
    if sum(c["bbox_px"][2] - c["bbox_px"][0] < 0.35 * (right - left) for c in chunks) < 0.6 * len(chunks):
        return None
    cells: dict[tuple[int, int], dict[str, Any]] = {}
    for r, row in enumerate(rows):
        for chunk in row:
            x0, x1 = chunk["bbox_px"][0], chunk["bbox_px"][2]
            spanned = [i for i, (c0, c1) in enumerate(columns) if min(x1, c1) - max(x0, c0) > 0]
            if not spanned:
                # No overlap: e.g. a left-aligned header over right-aligned numbers in a wide column.
                # It belongs to the first column whose values end at or after where it starts —
                # the column "slot" it begins in (nearest-centre would pick the previous column).
                spanned = [next((i for i, (_, c1) in enumerate(columns) if x0 <= c1), len(columns) - 1)]
            key = (r, spanned[0])
            if key in cells:
                cells[key]["text"] += " " + chunk["text"]
                cells[key]["words"] += chunk["words"]
            else:
                cells[key] = {"row": r, "column": spanned[0], "column_span": len(spanned), "text": chunk["text"],
                              "words": list(chunk["words"])}
    row_bounds = [[min(w["bbox_px"][1] for c in row for w in c["words"]), max(w["bbox_px"][3] for c in row for w in c["words"])]
                  for row in rows]
    result = []
    for r in range(len(rows)):
        for c in range(len(columns)):
            cell = cells.get((r, c))
            box = [columns[c][0], row_bounds[r][0], columns[c][1], row_bounds[r][1]]
            if cell:
                cell_words = cell.pop("words")
                box = [min(w["bbox_px"][0] for w in cell_words), row_bounds[r][0],
                       max(w["bbox_px"][2] for w in cell_words), row_bounds[r][1]]
                result.append({**cell, "bbox_px": box, "header": r == 0, "row_span": 1})
            elif not any(k[0] == r and k[1] < c < k[1] + v["column_span"] for k, v in cells.items()):
                result.append({"row": r, "column": c, "text": "", "bbox_px": box, "header": r == 0,
                               "row_span": 1, "column_span": 1, "state": "BLANK"})
    return {
        "rows": len(rows),
        "columns": len(columns),
        "column_bounds": columns,
        "row_bounds": row_bounds,
        "bbox_px": [left, row_bounds[0][0], right, row_bounds[-1][1]],
        "cells": result,
    }


def table_text(grid: dict[str, Any]) -> str:
    """Row-per-line text with ' | ' between cells: readable, and still searchable."""
    rows: dict[int, list[tuple[int, str]]] = {}
    for cell in grid["cells"]:
        rows.setdefault(cell["row"], []).append((cell["column"], cell["text"]))
    return "\n".join(" | ".join(text for _, text in sorted(rows[r])) for r in sorted(rows))


def find_table_zones(words: list[Word]) -> list[list[float]]:
    """Areas where consecutive lines share cell gaps: tables drawn with whitespace only."""
    if not words:
        return []
    height = _height(words)
    lines = _rows(words, tolerance=0.5 * height)
    candidate = [len(_chunks(line, gap=1.5 * height)) >= 2 for line in lines]
    zones: list[list[float]] = []
    start = None
    for index in range(len(lines) + 1):
        breaks = (
            index == len(lines)
            or not candidate[index]
            or (start is not None and lines[index][0]["bbox_px"][1] - max(w["bbox_px"][3] for w in lines[index - 1]) > 2.5 * height)
        )
        if start is None and index < len(lines) and candidate[index]:
            start = index
            continue
        if start is not None and breaks:
            run = [w for line in lines[start:index] for w in line]
            if index - start >= 3 and (grid := table_grid(run)):
                zones.append(grid["bbox_px"])
            start = index if index < len(lines) and candidate[index] else None
    return zones
