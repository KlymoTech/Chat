"""Local extraction/review exports and a real-image NVIDIA capability challenge.

Run with the repository's existing environment; no model settings are changed.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import secrets
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from northstar_api.services.extraction_benchmark import benchmark
from northstar_api.services.extraction_pipeline import extract_document
from northstar_api.services.extraction_schema import strict_json


async def run() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="A new output directory; existing directories are never overwritten")
    parser.add_argument("--probe-vision", action="store_true")
    parser.add_argument("--ground-truth", type=Path)
    args = parser.parse_args()
    if not args.source and not args.probe_vision:
        parser.error("Provide a source file or --probe-vision")
    args.output.mkdir(parents=True, exist_ok=False)
    from northstar_api.config import get_settings
    settings = get_settings()
    if args.probe_vision:
        from northstar_api.services.vision import read_image
        challenge = " ".join(str(secrets.randbelow(8000) + 1000) for _ in range(3))
        image = Image.new("RGB", (700, 140), "white")
        ImageDraw.Draw(image).text((30, 35), challenge, font=ImageFont.load_default(size=52), fill="black")
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        raw_image = buffer.getvalue()
        (args.output / "vision_challenge.png").write_bytes(raw_image)
        result = await read_image(raw_image, settings)
        passed = all(value in result for value in challenge.split())
        (args.output / "vision_probe.json").write_text(json.dumps({"provider": settings.extraction_vision_provider,
            "model": settings.extraction_vision_model, "expected": challenge, "observed": result,
            "status": "PASSED" if passed else "FAILED", "accuracy_benchmark": "NOT_MEASURED"}, indent=2), encoding="utf-8")
        if not passed:
            raise SystemExit("The endpoint did not recover the hidden image-only values; source processing is blocked.")
    if args.source:
        if args.source.stat().st_size > settings.upload_max_bytes:
            raise SystemExit("Source exceeds the configured upload limit")
        package = await extract_document(args.source.read_bytes(), args.source.name, settings)
        package.record["extraction_revision"] = 1
        (args.output / "evidence.zip").write_bytes(package.archive())
        (args.output / "extracted_review.txt").write_text(package.review_text(), encoding="utf-8")
        (args.output / "validation_report.txt").write_text(package.validation_text(), encoding="utf-8")
        (args.output / "extracted.json").write_text(json.dumps(package.record, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.ground_truth:
            truth = strict_json(args.ground_truth.read_text(encoding="utf-8"))
            (args.output / "benchmark.json").write_text(json.dumps(benchmark(package.record, truth), indent=2), encoding="utf-8")
        print(package.validation_text())


if __name__ == "__main__":
    asyncio.run(run())
