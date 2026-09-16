"""Source-preserving extraction; existing NVIDIA model and ingestion API unchanged."""
from __future__ import annotations

import asyncio
import codecs
import io
import json
import re
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import PurePath
from typing import TYPE_CHECKING, Any

from PIL import Image, ImageOps, ImageSequence

from northstar_api.services.extraction_evidence import (
    VALIDATOR_VERSION, deterministic_zip, leaf_blocks, read_zip, review_projection,
    sha256, valid_box, verify_projection,
)
from northstar_api.services.extraction_native import native_pdf, pdf_info, pdf_page
from northstar_api.services.extraction_regions import (
    PROMPT_VERSION, crop_image, read_native_gap, read_page, region_artifacts, review_dispute,
)
from northstar_api.services.extraction_schema import digest, strict_json
from northstar_api.services.extraction_validation import critical_page, disagreement, metrics, same_text, validate
from northstar_api.services.extraction_word import inspect_word, render_word

if TYPE_CHECKING:
    from northstar_api.config import Settings

PageCheckpoint = tuple[dict[str, Any], bytes, list[dict[str, Any]]]
PageCallback = Callable[[dict[str, Any], bytes, list[dict[str, Any]]], Awaitable[None]]


class CheckpointPersistenceError(RuntimeError):
    """Storage failure is not a source defect and must retry the worker."""


async def save_checkpoint(callback: PageCallback | None, page: dict[str, Any],
                          image: bytes, issues: list[dict[str, Any]]) -> None:
    if callback is not None:
        try:
            await callback(page, image, issues)
        except Exception as exc:
            raise CheckpointPersistenceError("Could not persist extraction checkpoint") from exc


def configuration(settings: Settings) -> dict[str, Any]:
    limits = {"upload_max_bytes", "knowledge_max_pdf_pages", "knowledge_max_docx_uncompressed_bytes",
              "knowledge_max_extracted_characters"}
    return {key: value for key, value in settings.model_dump().items()
            if key.startswith("extraction_") or key in limits}


@dataclass
class ExtractionPackage:
    record: dict[str, Any]
    images: dict[str, bytes]

    @property
    def issues(self) -> list[dict[str, Any]]:
        return self.record["issues"]

    def refresh(self) -> None:
        self.record["checks"] = validate(self.record, self.images)
        self.record["metrics"] = metrics(self.record)
        self.record["validator_version"] = VALIDATOR_VERSION
        passed = all(check["status"] == "PASSED" for check in self.record["checks"])
        self.record["release_eligible"] = passed
        if self.record["review_status"] == "verified_release" and not passed:
            self.record["review_status"] = "needs_review"
        self.record["release_blockers"] = [c["name"] for c in self.record["checks"] if c["status"] != "PASSED"]
        self.record["draft_available"] = True
        self.record["measured_extraction_accuracy"] = "NOT_MEASURED"

    def review_text(self) -> str:
        self.refresh()
        text = review_projection(self.record)
        verify_projection(text, self.record)
        return text

    def validation_text(self) -> str:
        self.refresh()
        lines = [f"Source SHA-256: {self.record['source_sha256']}",
                 f"Extraction revision: {self.record.get('extraction_revision')}",
                 f"Configuration SHA-256: {self.record.get('config_sha256')}",
                 f"Validator version: {VALIDATOR_VERSION}",
                 f"Expected units: {self.record['expected_units']}",
                 f"Processed units: {len(self.record['pages'])}",
                 f"Vision model: {self.record.get('vision_model') or 'NOT_APPLICABLE'}",
                 "Measured accuracy: NOT_MEASURED",
                 f"Verified release: {'APPROVED' if self.record['review_status'] == 'verified_release' and self.record['release_eligible'] else 'BLOCKED'}",
                 "Draft review export: AVAILABLE"]
        for stage in self.record.get("stages", []):
            lines.append("STAGE " + json.dumps(stage, ensure_ascii=False, sort_keys=True))
        for check in self.record["checks"]:
            lines.append(f"{check['name']}: {check['status']} " + json.dumps(check["details"], ensure_ascii=False))
        lines.extend(json.dumps(issue, ensure_ascii=False, sort_keys=True) for issue in self.issues)
        return "\n".join(lines) + "\n"

    def archive(self) -> bytes:
        self.refresh()
        validation = self.validation_text().encode()
        report = self.review_text().encode()
        canonical = json.dumps(self.record, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode()
        verify_projection(report.decode(), json.loads(canonical))
        artifacts = {**self.images, "extracted.json": canonical, "extracted_review.txt": report,
                     "validation_report.txt": validation,
                     "correction_history.json": json.dumps(self.record.get("correction_history", []), ensure_ascii=False, sort_keys=True).encode()}
        manifest = {"schema_version": 2, "extraction_revision": self.record.get("extraction_revision"),
                    "source_sha256": self.record["source_sha256"], "prompt_version": PROMPT_VERSION,
                    "validator_version": VALIDATOR_VERSION, "config_sha256": self.record.get("config_sha256"),
                    "parsers": self.record.get("parsers"), "vision_model": self.record.get("vision_model"),
                    "vision_provider": self.record.get("vision_provider"), "expected_units": self.record["expected_units"],
                    "expanded_artifact_bytes": sum(map(len, artifacts.values())),
                    "artifacts": {name: sha256(data) for name, data in artifacts.items()}}
        artifacts["manifest.json"] = json.dumps(manifest, sort_keys=True, indent=2).encode()
        return deterministic_zip(artifacts)


def encode_page_checkpoint(page: dict[str, Any], image: bytes, page_issues: list[dict[str, Any]], *,
                           source_sha256: str, model: str, version: int) -> bytes:
    metadata = {"checkpoint_schema_version": 2, "source_sha256": source_sha256, "model": model,
                "prompt_version": PROMPT_VERSION, "version": version, "page": page,
                "issues": page_issues, "image_sha256": sha256(image)}
    encoded = json.dumps(metadata, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    return deterministic_zip({"page.json": encoded, "image.png": image,
                              "metadata.sha256": sha256(encoded).encode("ascii")})


def decode_page_checkpoint(data: bytes, *, source_sha256: str, model: str,
                           version: int, page_number: int) -> PageCheckpoint:
    members = read_zip(data, max_bytes=100 * 1024**2, max_members=3)
    if set(members) != {"page.json", "image.png", "metadata.sha256"}:
        raise ValueError("Checkpoint artifact set is invalid; retry extraction")
    if sha256(members["page.json"]).encode("ascii") != members["metadata.sha256"]:
        raise ValueError("Checkpoint metadata checksum failed")
    metadata = strict_json(members["page.json"], max_bytes=100 * 1024**2)
    page = metadata.get("page")
    image = members["image.png"]
    if (metadata.get("checkpoint_schema_version") != 2 or metadata.get("source_sha256") != source_sha256
        or metadata.get("model") != model or metadata.get("prompt_version") != PROMPT_VERSION
        or metadata.get("version") != version or not isinstance(page, dict)
        or page.get("source_sha256") != source_sha256 or page.get("number") != page_number
        or metadata.get("image_sha256") != sha256(image) or page.get("image_sha256") != sha256(image)
        or not isinstance(metadata.get("issues"), list)):
        raise ValueError("Checkpoint source identity or image checksum failed")
    return page, image, metadata["issues"]


def _compare(native: str, visual: str) -> bool:
    return same_text(native, visual)


async def _read_image(image: bytes, settings: Settings) -> str:
    from northstar_api.services.vision import read_image
    return await read_image(image, settings)


def text_unit(data: bytes) -> dict[str, Any]:
    encoding, bom = "utf-8", b""
    for marker, codec in ((codecs.BOM_UTF32_LE, "utf-32-le"), (codecs.BOM_UTF32_BE, "utf-32-be"),
                          (codecs.BOM_UTF8, "utf-8"), (codecs.BOM_UTF16_LE, "utf-16-le"), (codecs.BOM_UTF16_BE, "utf-16-be")):
        if data.startswith(marker):
            encoding, bom = codec, marker
            break
    text = data[len(bom):].decode(encoding, errors="strict")
    offset, char_offset = len(bom), 0
    lines = []
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        size = len(line.encode(encoding))
        lines.append({"number": number, "byte_start": offset, "byte_end": offset + size,
                      "char_start": char_offset, "char_end": char_offset + len(line), "text": line})
        offset += size
        char_offset += len(line)
    return {"number": 1, "source_page_index": None, "source_page_number": None,
            "rendered_page_number": None, "source_unit": "bytes", "native_text": text, "visual_text": None,
            "selected_text": text, "image": None, "requires_image": False, "encoding": encoding,
            "bom_hex": bom.hex(), "line_endings": sorted(set(re.findall(r"\r\n|\r|\n", text))),
            "lines": lines, "line_byte_offsets": [line["byte_start"] for line in lines], "blocks": [],
            "blank": not text, "inventory_complete": True}


def inside(inner: list[float], outer: list[float]) -> bool:
    return outer[0] <= (inner[0] + inner[2]) / 2 <= outer[2] and outer[1] <= (inner[1] + inner[3]) / 2 <= outer[3]


def _parser_versions() -> dict[str, str]:
    values = {}
    for name in ("pymupdf", "pypdf", "python-docx", "pillow", "langchain-nvidia-ai-endpoints"):
        try:
            values[name] = version(name)
        except PackageNotFoundError:
            values[name] = "NOT_INSTALLED"
    return values


async def extract_document(data: bytes, filename: str, settings: Settings, *,
                           resume_pages: dict[int, PageCheckpoint] | None = None,
                           on_page: PageCallback | None = None) -> ExtractionPackage:
    suffix = PurePath(filename.replace("\\", "/")).suffix.lower().lstrip(".")
    if suffix not in {"pdf", "docx", "png", "jpg", "jpeg", "tif", "tiff", "txt", "md", "markdown"}:
        raise ValueError("Unsupported source extension")
    if len(data) > settings.upload_max_bytes or len(data) > settings.extraction_max_evidence_bytes:
        raise ValueError("Source exceeds upload/evidence size limit")
    source_hash = sha256(data)
    pages: list[dict[str, Any]] = []
    artifacts: dict[str, bytes] = {f"source/original.{suffix}": data}
    issues: list[dict[str, Any]] = []
    config = configuration(settings)
    record: dict[str, Any] = {"schema_version": 2, "extraction_revision": None,
        "source_name": filename, "source_sha256": source_hash, "config": config, "config_sha256": digest(config),
        "pages": pages, "issues": issues, "vision_model": settings.extraction_vision_model,
        "vision_provider": settings.extraction_vision_provider, "review_status": "needs_review",
        "approved_pages": [], "correction_history": [], "stages": [], "parsers": _parser_versions()}
    resume_pages = {number: checkpoint for number, checkpoint in (resume_pages or {}).items() if not checkpoint[0].get("failure_code")}

    def issue(number: int, code: str, message: str, block_id: str | None = None, technical: bool = False) -> None:
        issues.append({"id": f"I{len(issues) + 1:06d}", "page": number, "code": code, "message": message,
                       "block_id": block_id, "technical": technical, "status": "open",
                       "severity": "CRITICAL" if technical or code in {"NUMERIC_CONFLICT", "CRITICAL_WORD_CONFLICT", "CRITICAL_SYMBOL_CONFLICT"} else "REVIEW"})

    async def failed_page(number: int, code: str, message: str, unit: str = "page") -> None:
        issue(number, code, message, technical=True)
        pages.append({"number": number, "source_sha256": source_hash, "source_page_index": number - 1,
                      "source_page_number": number, "rendered_page_number": None, "source_unit": unit,
                      "native_text": "", "visual_text": None, "selected_text": None, "image": None,
                      "requires_image": unit != "bytes", "blocks": [], "inventory_complete": False,
                      "config_sha256": record["config_sha256"], "failure_code": code,
                      "image_sha256": sha256(b""), "prompt_version": PROMPT_VERSION})
        if on_page:
            # A failed-unit checkpoint has no source image. It is reprocessed on
            # resume, while later successful checkpoints remain reusable.
            await save_checkpoint(on_page, pages[-1], b"", [issues[-1]])

    async def process(number: int, image: bytes, native: str, details: dict[str, Any]) -> None:
        start = len(issues)
        if number in resume_pages:
            saved, saved_image, saved_issues = deepcopy(resume_pages[number])
            if (saved.get("config_sha256") != record["config_sha256"] or saved.get("source_sha256") != source_hash
                or saved.get("number") != number or saved.get("image_sha256") != sha256(saved_image)
                or saved.get("prompt_version") != PROMPT_VERSION):
                raise ValueError("Checkpoint identity/configuration changed; retry with a new revision")
            page, image = saved, saved_image
            for value in saved_issues:
                issues.append({**value, "id": f"I{len(issues) + 1:06d}"})
        else:
            with Image.open(io.BytesIO(image)) as bitmap:
                width, height = bitmap.size
            page = {"number": number, "source_sha256": source_hash, "source_page_index": number - 1,
                    "source_page_number": number, "rendered_page_number": number, "printed_page_label": None,
                    "source_unit": "page", "native_text": native, "image": f"pages/page_{number:04d}.png",
                    "image_sha256": sha256(image), "width_px": width, "height_px": height,
                    "requires_image": True, "selected_text": None, "config_sha256": record["config_sha256"], **details}
            visual = await read_page(image, number, settings)
            for problem in visual.pop("problems"):
                issue(number, **problem)
            page.update(visual)
            for native_block in page.get("native_blocks", []):
                if not any(inside(native_block["bbox_px"], b["bbox_px"]) for b in leaf_blocks(page)):
                    if valid_box(native_block["bbox_px"], width, height):
                        await read_native_gap(image, page, native_block, settings)
                    issue(number, "NATIVE_REGION_UNACCOUNTED", f"Review recovered native object {native_block['id']} and its reading order")
            leaves = leaf_blocks(page)
            page["visual_text"] = "\n".join((b.get("visual") or {}).get("text", "") for b in leaves)
            for order, block in enumerate(leaves):
                block["reading_order"] = order
                selected_words = [w for w in page.get("native_words", []) if inside(w["bbox_px"], block["bbox_px"])]
                block["native_text"] = " ".join(w["text"] for w in selected_words)
                reading = block.get("visual")
                if reading:
                    block["agreement"] = bool(block["native_text"]) and same_text(block["native_text"], reading["text"])
                    if block["agreement"]:
                        block["selected_text"] = reading["text"]
                        block["selection_basis"] = "candidate_agreement_pending_source_review"
                    elif block["native_text"]:
                        issue(number, disagreement(block["native_text"], reading["text"]), "Native and independent visual region candidates differ", block["id"])
                        await review_dispute(image, page, block, settings)
                if block["status"] == "failed" and not any(i["block_id"] == block["id"] and i["technical"] for i in issues[start:]):
                    issue(number, "VISION_UNAVAILABLE", "Independent region reading failed", block["id"], True)
                block["requires_second_review"] = block["type"] in {"table", "equation", "question", "answer_key"}
            if native and not same_text(native, page["visual_text"]):
                issue(number, disagreement(native, page["visual_text"]), "Whole-page candidates disagree; inspect reading order, signs and coverage")
            if page.get("native_table_error"):
                issue(number, "NATIVE_TABLE_CHECK_FAILED", "Native table inspection failed; inspect every table cell")
            for table in page.get("native_tables", []):
                candidates = [b for b in leaves if b["type"] == "table" and inside(table["bbox_px"], b["bbox_px"])]
                if not candidates:
                    issue(number, "TABLE_STRUCTURE_UNKNOWN", "Native table has no visual-table counterpart")
                else:
                    cells = (candidates[0].get("visual") or {}).get("cells", [])
                    candidates[0]["native_table"] = table
                    for row_index, row in enumerate(table["rows"]):
                        for column, value in enumerate(row):
                            if value is not None and not any(c["row"] == row_index and c["column"] == column and same_text(value, c["text"]) for c in cells):
                                issue(number, "TABLE_CELL_CONFLICT", f"Native cell R{row_index}C{column} differs from its visual cell", candidates[0]["id"])
            for index, left in enumerate(leaves):
                for right in leaves[index + 1:]:
                    a, b = left["bbox_px"], right["bbox_px"]
                    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
                    if overlap > .1 * min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])):
                        issue(number, "REGION_OVERLAP", f"Source regions {left['id']} and {right['id']} overlap")
            if leaves and all(b.get("selected_text") is not None for b in leaves):
                page["selected_text"] = "\n".join(b["selected_text"] for b in leaves)
            elif page.get("blank") and not native:
                page["selected_text"] = ""
            page["requires_second_review"] = critical_page(page)
            if not issues[start:]:
                issue(number, "SOURCE_REVIEW_REQUIRED", "Compare the entire source page and all detected regions before approval")
        page_artifacts = {page["image"]: image, **region_artifacts(page, image)}
        if sum(map(len, artifacts.values())) + sum(map(len, page_artifacts.values())) > settings.extraction_max_evidence_bytes:
            del issues[start:]
            await failed_page(number, "EVIDENCE_LIMIT", "Page evidence exceeds the configured budget; original source retained")
            return
        pages.append(page)
        artifacts.update(page_artifacts)
        await save_checkpoint(on_page, page, image, issues[start:])

    record["stages"].append({"stage": "inspect", "status": "complete"})
    word, pdf_data = None, None
    if suffix == "docx":
        try:
            word, derivative = await asyncio.to_thread(inspect_word, data, settings)
            record["word"] = word
            artifacts["derivatives/frozen.docx"] = derivative
            if word["render_blockers"]:
                raise ValueError("WORD_UNSAFE_RENDER_DEPENDENCY")
            rendered, renderer = await asyncio.to_thread(render_word, derivative, settings)
            word["renderer"] = renderer
            artifacts["derivatives/rendered.pdf"] = rendered
            if sum(map(len, artifacts.values())) > settings.extraction_max_evidence_bytes:
                del artifacts["derivatives/rendered.pdf"]
                raise ValueError("WORD_DERIVATIVE_EVIDENCE_LIMIT")
            pdf_data = rendered
        except CheckpointPersistenceError:
            raise
        except Exception as exc:
            await failed_page(1, "WORD_RENDER_REQUIRED", f"Controlled Word parsing/rendering unavailable ({type(exc).__name__})", "logical_document")
            pages[-1].update(source_page_index=None, source_page_number=None)
            if word:
                pages[-1]["native_text"] = "\n".join(b["text"] for b in word["blocks"] if b["part"] == "word/document.xml" and b["type"] == "paragraph" and b["channel"] == "visible_candidate")
    elif suffix == "pdf":
        pdf_data = data
    if pdf_data is not None:
        try:
            info = await pdf_info(pdf_data, settings)
        except Exception as exc:
            await failed_page(1, "PDF_INSPECTION_FAILED", f"PDF source could not be inventoried ({type(exc).__name__})")
            info = None
        if info and info["encrypted"]:
            record.update(review_status="needs_password", expected_units=0)
            issue(0, "NEEDS_PASSWORD", "Supply a source unlocked with its password", technical=True)
        elif info:
            count = info["count"]
            record["expected_units"] = count
            for index in range(count):
                number = index + 1
                if number in resume_pages:
                    await process(number, resume_pages[number][1], "", {})
                    continue
                if sum(map(len, artifacts.values())) >= settings.extraction_max_evidence_bytes:
                    await failed_page(number, "EVIDENCE_LIMIT", "Evidence budget reached; original source retained")
                    continue
                try:
                    image, native, details = await pdf_page(pdf_data, index, settings)
                except Exception as exc:
                    await failed_page(number, "PAGE_RENDER_FAILED", f"Native page parsing/rendering failed ({type(exc).__name__})")
                    continue
                details["pdf_page_label"] = info["labels"][index] if index < len(info["labels"]) else None
                details["source_unit"] = "word_rendered_page" if word else "pdf_page"
                if word:
                    details["rendered_derivative_sha256"] = sha256(pdf_data)
                    details["source_page_index"] = None
                    details["source_page_number"] = None
                await process(number, image, native, details)
    elif suffix in {"png", "jpg", "jpeg", "tif", "tiff"}:
        try:
            with Image.open(io.BytesIO(data)) as original:
                count = getattr(original, "n_frames", 1)
                if count > settings.knowledge_max_pdf_pages:
                    raise ValueError("Image source exceeds frame limit")
                record["expected_units"] = count
                for index, frame in enumerate(ImageSequence.Iterator(original)):
                    if index + 1 in resume_pages:
                        await process(index + 1, resume_pages[index + 1][1], "", {})
                        continue
                    try:
                        if frame.width * frame.height > 100_000_000:
                            raise ValueError("Image source exceeds pixel limit")
                        original_size = list(frame.size)
                        orientation = frame.getexif().get(274, 1)
                        oriented = ImageOps.exif_transpose(frame).convert("RGB")
                        ratio = min(1., (settings.extraction_max_image_pixels / (oriented.width * oriented.height)) ** .5)
                        if ratio < 1:
                            oriented = oriented.resize((max(1, round(oriented.width * ratio)), max(1, round(oriented.height * ratio))))
                        output = io.BytesIO()
                        oriented.save(output, format="PNG")
                        await process(index + 1, output.getvalue(), "", {"source_unit": "image_frame", "source_frame_index": index,
                            "original_dimensions_px": original_size, "original_exif_orientation": orientation,
                            "exif_orientation_applied": True, "render_scale": ratio,
                            "source_to_render": {"exif_orientation": orientation, "resize_scale": ratio}})
                    except CheckpointPersistenceError:
                        raise
                    except Exception as exc:
                        # Do not restart or drop preceding successful frames.
                        if len(pages) <= index:
                            await failed_page(index + 1, "IMAGE_FRAME_FAILED", f"Image frame failed ({type(exc).__name__})", "image_frame")
        except CheckpointPersistenceError:
            raise
        except Exception as exc:
            if not pages:
                await failed_page(1, "IMAGE_INSPECTION_FAILED", f"Image cannot be inventoried ({type(exc).__name__})", "image_frame")
            for number in range(len(pages) + 1, record.get("expected_units", len(pages)) + 1):
                await failed_page(number, "IMAGE_FRAME_FAILED", "Frame unavailable after source decoding failure", "image_frame")
    elif suffix in {"txt", "md", "markdown"}:
        record.update(expected_units=1, vision_model=None, vision_provider=None)
        try:
            page = text_unit(data)
            page.update(source_sha256=source_hash, config_sha256=record["config_sha256"])
            pages.append(page)
        except UnicodeDecodeError:
            await failed_page(1, "ENCODING_REQUIRED", "Strict decoding failed; supply UTF-8 or BOM-labelled UTF-16/32", "bytes")
    record.setdefault("expected_units", len(pages))
    if word and pdf_data:
        for block in word["blocks"]:
            value = re.sub(r"\s+", " ", block["text"]).strip()
            matches = [p["number"] for p in pages if value and value in re.sub(r"\s+", " ", p["native_text"])]
            block["rendered_pages"] = matches
            block["mapping_status"] = "matched" if len(matches) == 1 else "ambiguous"
            if block["part"] == "word/document.xml" and block["type"] == "paragraph" and block["channel"] == "visible_candidate" and value and len(matches) != 1:
                issue(matches[0] if matches else 1, "WORD_MAPPING_AMBIGUOUS", f"Logical source {block['id']} needs source-to-page mapping review")
    for page in pages:
        for block in leaf_blocks(page):
            reading = block.get("visual") or {}
            if reading.get("continues_from_previous") or reading.get("continues_on_next"):
                issue(page["number"], "CONTINUITY_REVIEW", "Confirm reciprocal source fragment relationships", block["id"])
    if sum(len(p.get("native_text", "")) + len(p.get("visual_text") or "") for p in pages) > settings.knowledge_max_extracted_characters:
        issue(0, "TEXT_LIMIT", "Extracted candidates exceed configured text limit", technical=True)
    required = [p for p in pages if p.get("requires_image")]
    def stage(name: str, completed: int, total: int) -> None:
        record["stages"].append({"stage": name, "status": "not_applicable" if not total else "complete" if completed == total else "partial" if completed else "failed",
                                 "completed_units": completed, "expected_units": total})
    stage("native_extract", sum(not p.get("failure_code") for p in pages if p.get("source_unit") != "image_frame"),
          len([p for p in pages if p.get("source_unit") != "image_frame"]))
    stage("render", sum(bool(p.get("image")) for p in required), len(required))
    stage("visual_inventory", sum(bool(p.get("inventory_complete")) for p in required), len(required))
    stage("region_reading", sum(bool(p.get("inventory_complete")) and all((b.get("visual") or {}).get("complete") for b in leaf_blocks(p)) for p in required), len(required))
    stage("reconcile", sum(p.get("selected_text") is not None for p in pages), len(pages))
    record["stages"].append({"stage": "human_review", "status": "pending"})
    package = ExtractionPackage(record, artifacts)
    package.refresh()
    return package
