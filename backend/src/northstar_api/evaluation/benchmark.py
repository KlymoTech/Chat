"""Run the extraction pipeline over the gold set and score it.

Offline (default, used in CI): no vision model is called. It measures the deterministic core —
layout, reading order, table cells and the text-layer drafts — and whether anything was wrongly
auto-accepted. With OCR installed, scanned documents and 2-of-3 consensus are measured too.

    python -m northstar_api.evaluation.benchmark --out report.json          # offline
    python -m northstar_api.evaluation.benchmark --live --out report.json   # with the vision model
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

from northstar_api.config import Settings
from northstar_api.evaluation.gold import GoldDocument, gold_documents
from northstar_api.evaluation.scoring import score_page
from northstar_api.services import hybrid_extraction


@contextmanager
def _vision_disabled() -> Any:
    async def unavailable(_settings: Settings) -> tuple[dict[str, Any], bytes]:
        return {"status": "FAILED", "model": "disabled-for-offline-benchmark", "purpose": "image_transport_probe"}, b""

    with patch.object(hybrid_extraction, "verify_image_capability", unavailable):
        yield


async def score_document(document: GoldDocument, settings: Settings) -> dict[str, Any]:
    package = await hybrid_extraction.extract_document(document.pdf, f"{document.name}.pdf", settings)
    pages = package.record["pages"]
    truth = document.truth()["pages"]
    scores = [score_page(t, p) for t, p in zip(truth, pages, strict=False)]
    ocr = {p.get("ocr", {}).get("status") for p in pages} - {None}
    return {
        "name": document.name,
        "description": document.description,
        "scanned": document.scanned,
        "ocr": sorted(ocr),
        "pages": scores,
        "technical_issues": sum(1 for i in package.issues if i.get("technical")),
        "review_issues": sum(1 for i in package.issues if not i.get("technical")),
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    pages = [p for r in results for p in r["pages"]]

    def mean(key: str) -> float | None:
        values = [p[key] for p in pages if p.get(key) is not None]
        return round(sum(values) / len(values), 5) if values else None

    return {
        "documents": len(results),
        "pages": len(pages),
        "mean_cer": mean("cer"),
        "mean_wer": mean("wer"),
        "mean_reading_order": mean("reading_order"),
        "mean_table_cell_accuracy": mean("table_cell_accuracy"),
        "settled_regions": sum(p["settled_regions"] for p in pages),
        "regions": sum(p["regions"] for p in pages),
        "false_accepts": sum(len(p["false_accepts"]) for p in pages),
        "technical_issues": sum(r["technical_issues"] for r in results),
    }


async def run(settings: Settings, *, live: bool = False, include_scanned: bool = True) -> dict[str, Any]:
    documents = gold_documents(include_scanned=include_scanned)
    results = []
    if live:
        for document in documents:
            results.append(await score_document(document, settings))
    else:
        with _vision_disabled():
            for document in documents:
                results.append(await score_document(document, settings))
    return {"mode": "live" if live else "offline", "summary": summarize(results), "documents": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help="call the configured vision model")
    parser.add_argument("--no-scanned", action="store_true", help="skip image-only documents")
    parser.add_argument("--out", help="write the full JSON report here")
    args = parser.parse_args()
    report = asyncio.run(run(Settings(), live=args.live, include_scanned=not args.no_scanned))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
    json.dump(report["summary"], sys.stdout, indent=2)
    print()
    for document in report["documents"]:
        for number, page in enumerate(document["pages"], 1):
            print(f"{document['name']:<28} p{number}  CER {page['cer']:.4f}  WER {page['wer']:.4f}  "
                  f"order {page['reading_order']:.3f}  tables {page['table_cell_accuracy']}  "
                  f"settled {page['settled_regions']}/{page['regions']}  false-accepts {len(page['false_accepts'])}")


if __name__ == "__main__":
    main()
