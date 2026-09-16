"""Source-preserving extraction, independent vision and resumable evidence assembly."""
from __future__ import annotations

import asyncio
import hashlib
import io
from copy import deepcopy
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING, Any

import fitz
from PIL import Image, ImageOps, ImageSequence
from pypdf import PdfReader

from northstar_api.services.extraction_checkpoint import PageCallback, PageCheckpoint, resumable
from northstar_api.services.extraction_native import configuration, inside, native_pdf, text_unit
from northstar_api.services.extraction_package import ExtractionPackage
from northstar_api.services.extraction_regions import PROMPT_VERSION, read_page, region_artifacts
from northstar_api.services.extraction_schema import digest
from northstar_api.services.extraction_validation import critical_page, disagreement, same_text
from northstar_api.services.extraction_word import inspect_word, render_word

if TYPE_CHECKING:
    from northstar_api.config import Settings


def parser_versions() -> dict[str, str]:
    result = {}
    for package in ("pymupdf", "pypdf", "python-docx", "pillow", "langchain-nvidia-ai-endpoints"):
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = "NOT_INSTALLED"
    return result


class CheckpointWriteError(RuntimeError):
    """A durable write failed; let the job retry instead of hiding it as a source defect."""


async def extract_document(data: bytes, filename: str, settings: Settings, *,
                           resume_pages: dict[int, PageCheckpoint] | None = None,
                           on_page: PageCallback | None = None,
                           previous_package: ExtractionPackage | None = None) -> ExtractionPackage:
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix not in {"pdf", "docx", "png", "jpg", "jpeg", "tif", "tiff", "txt", "md", "markdown"}:
        raise ValueError("Unsupported extraction source; use PDF, DOCX, PNG/JPEG/TIFF, or strict text")
    if len(data) > settings.upload_max_bytes or len(data) > settings.extraction_max_evidence_bytes:
        raise ValueError("Source exceeds upload or evidence limits")
    source_hash = hashlib.sha256(data).hexdigest()
    config = configuration(settings)
    config_hash = digest(config)
    pages: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    artifacts: dict[str, bytes] = {f"source/original.{suffix}": data}
    old = previous_package.record if previous_package else {}
    reuse_previous = bool(old.get("source_sha256") == source_hash and old.get("config_sha256") == config_hash
                          and old.get("parsers") == parser_versions() and old.get("prompt_version") == PROMPT_VERSION)
    checkpoints = dict(resume_pages or {})
    if reuse_previous and previous_package:
        for page in old.get("pages", []):
            page_issues = [item for item in old.get("issues", []) if item.get("page") == page["number"]]
            path = page.get("image")
            if page["number"] not in checkpoints and path in previous_package.images and resumable(page, page_issues):
                checkpoints[page["number"]] = (deepcopy(page), previous_package.images[path], deepcopy(page_issues))
    record: dict[str, Any] = {"schema_version": 2, "extraction_revision": None, "source_name": filename,
                              "source_sha256": source_hash, "config": config, "config_sha256": config_hash,
                              "pages": pages, "issues": issues, "vision_model": settings.extraction_vision_model,
                              "vision_provider": "nvidia", "prompt_version": PROMPT_VERSION,
                              "review_status": "needs_review", "approved_pages": [], "stages": [],
                              "correction_history": deepcopy(old.get("correction_history", [])) if reuse_previous else [],
                              "parsers": parser_versions(), "reused_units": [], "reprocessed_units": []}

    def issue(number: int, code: str, message: str, block_id: str | None = None, technical: bool = False) -> None:
        signature = {"page": number, "code": code, "message": message, "block_id": block_id}
        identifier = "I-" + digest(signature)[:20]
        if any(item["id"] == identifier for item in issues):
            return
        issues.append({**signature, "id": identifier, "technical": technical, "status": "open",
                       "severity": "CRITICAL" if technical or code in {"NUMERIC_CONFLICT", "CRITICAL_WORD_CONFLICT", "SYMBOL_CONFLICT"} else "REVIEW"})

    def add_artifacts(values: dict[str, bytes]) -> bool:
        size = sum(len(value) for value in artifacts.values()) + sum(len(value) for key, value in values.items() if key not in artifacts)
        if size > settings.extraction_max_evidence_bytes:
            return False
        artifacts.update(values)
        return True

    def failed_unit(number: int, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        pages.append({"number": number, "source_page_index": number - 1, "source_page_number": number,
                      "rendered_page_number": number, "source_unit": "page", "native_text": "", "visual_text": None,
                      "selected_text": None, "image": None, "requires_image": True, "inventory_complete": False,
                      "blocks": [], "config_sha256": config_hash, **(details or {})})
        issue(number, code, message, technical=True)

    async def process(number: int, image: bytes, native: str, details: dict[str, Any], *, verify_cached_image: bool = False) -> None:
        cached = checkpoints.get(number)
        if cached:
            saved, saved_image, saved_issues = cached
            if (saved.get("config_sha256") != config_hash or not resumable(saved, saved_issues)
                    or hashlib.sha256(saved_image).hexdigest() != saved.get("image_sha256")
                    or (verify_cached_image and hashlib.sha256(image).hexdigest() != saved.get("image_sha256"))):
                cached = None
        if cached:
            saved, saved_image, saved_issues = cached
            page = deepcopy(saved)
            image = saved_image
            issues.extend(deepcopy([item for item in saved_issues if item["id"] not in {i["id"] for i in issues}]))
            record["reused_units"].append(number)
        else:
            with Image.open(io.BytesIO(image)) as bitmap:
                width, height = bitmap.size
            page = {"number": number, "source_page_index": number - 1, "source_page_number": number,
                    "rendered_page_number": number, "source_unit": "page", "printed_page_label": None,
                    "native_text": native, "selected_text": None, "image": f"pages/page_{number:04d}.png",
                    "image_sha256": hashlib.sha256(image).hexdigest(), "width_px": width, "height_px": height,
                    "requires_image": True, "config_sha256": config_hash, **details}
            visual = await read_page(image, number, settings)
            for problem in visual.pop("problems"):
                issue(number, problem["code"], problem["message"], problem.get("block_id"), problem.get("technical", False))
            page.update(visual)
            leaves = [block for block in page["blocks"] if block["status"] != "split"]
            for block in leaves:
                selected_words = [word["text"] for word in details.get("native_words", []) if inside(word["bbox_px"], block["bbox_px"])]
                block["native_text"] = " ".join(selected_words)
                reading = block.get("visual")
                if reading:
                    block["agreement"] = bool(block["native_text"]) and same_text(block["native_text"], reading["text"])
                    if block["agreement"] and block["type"] == reading["kind"]:
                        block["selected_text"] = reading["text"]
                    elif block["native_text"] and not block["agreement"]:
                        issue(number, disagreement(block["native_text"], reading["text"]), "Native and visual region candidates disagree", block["id"])
            inventory = []
            for native_block in details.get("native_blocks", []):
                owners = [block["id"] for block in leaves if inside(native_block["bbox_px"], block["bbox_px"])]
                inventory.append({"native_id": native_block["id"], "region_ids": owners,
                                  "disposition": "ALIGNED" if owners else "UNRESOLVED"})
                if not owners:
                    issue(number, "NATIVE_REGION_UNACCOUNTED", f"Native object {native_block['id']} is not represented in the visual inventory")
            for channel in ("annotations", "form_fields"):
                for index, item in enumerate(details.get(channel, [])):
                    inventory.append({"native_id": f"{channel}:{index}", "disposition": "PRESERVED_NATIVE_METADATA", "evidence": item})
            page["source_inventory"] = inventory
            if native and not same_text(native, page["visual_text"]):
                issue(number, disagreement(native, page["visual_text"]), "Page-wide candidates differ; inspect ordering and omitted content")
            if details.get("native_table_error"):
                issue(number, "NATIVE_TABLE_INSPECTION_FAILED", "Native table inspection failed", technical=True)
            for table in details.get("native_tables", []):
                candidates = [block for block in leaves if block["type"] == "table" and inside(table["bbox_px"], block["bbox_px"])]
                if len(candidates) != 1:
                    issue(number, "TABLE_STRUCTURE_UNKNOWN", "Native table needs a unique structured visual counterpart")
                    continue
                cells = {(cell["row"], cell["column"]): cell["text"] for cell in (candidates[0].get("visual") or {}).get("cells", [])}
                for row_index, row in enumerate(table["rows"]):
                    for column_index, value in enumerate(row):
                        if value is not None and not same_text(str(value), cells.get((row_index, column_index), "")):
                            issue(number, "TABLE_CELL_CONFLICT", f"Native/visual cell differs at row {row_index}, column {column_index}", candidates[0]["id"])
            for index, left in enumerate(leaves):
                a = left["bbox_px"]
                for right in leaves[index + 1:]:
                    b = right["bbox_px"]
                    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
                    area = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
                    if overlap > area * 0.1:
                        issue(number, "REGION_OVERLAP", f"Regions {left['id']} and {right['id']} overlap")
            if leaves and all(block.get("selected_text") is not None for block in leaves):
                page["selected_text"] = "\n".join(block["selected_text"] for block in leaves)
            elif page["blank"] and not native:
                page["selected_text"] = ""
            page["requires_second_review"] = critical_page(page)
            if not any(item["page"] == number for item in issues):
                issue(number, "SOURCE_REVIEW_REQUIRED", "Compare this source unit against its retained evidence")
            record["reprocessed_units"].append(number)
        evidence = {page["image"]: image, **region_artifacts(page, image)}
        if not add_artifacts(evidence):
            issue(number, "EVIDENCE_LIMIT", "Page/crop evidence exceeds the configured limit", technical=True)
            # Keep the readable draft metadata; missing evidence blocks release.
        pages.append(page)
        page_issues = [item for item in issues if item["page"] == number]
        if on_page and resumable(page, page_issues) and all(name in artifacts for name in evidence):
            try:
                await on_page(page, image, page_issues)
            except Exception as exc:
                raise CheckpointWriteError("Page checkpoint persistence failed") from exc

    pdf_data: bytes | None = data if suffix == "pdf" else None
    word: dict[str, Any] | None = None
    try:
        if suffix == "docx":
            word, frozen = inspect_word(data, settings)
            record["word"] = word
            if not add_artifacts({"source/word_frozen.docx": frozen}):
                raise ValueError("WORD_EVIDENCE_LIMIT")
            if word["render_blockers"]:
                raise ValueError("WORD_RENDER_DEPENDENCY_BLOCKED")
            pdf_data, renderer = await asyncio.to_thread(render_word, frozen, settings)
            word["renderer"] = renderer
            if reuse_previous and old.get("word", {}).get("parts") == word["parts"] and old.get("word", {}).get("renderer") == renderer:
                old_blocks = {block["id"]: block for block in old["word"].get("blocks", [])}
                for block in word["blocks"]:
                    previous = old_blocks.get(block["id"], {})
                    if previous.get("xml") == block["xml"] and previous.get("mapping_status") == "source_reviewed":
                        for key in ("rendered_pages", "mapping_status", "mapping_evidence_block_ids", "mapping_review_reason"):
                            if key in previous:
                                block[key] = previous[key]
            if not add_artifacts({"source/word_rendered.pdf": pdf_data}):
                raise ValueError("WORD_EVIDENCE_LIMIT")
        record["stages"].append({"stage": "inspect", "status": "complete"})
    except Exception as exc:
        issue(0, "WORD_RENDER_REQUIRED", f"Controlled Word derivative unavailable ({type(exc).__name__})", technical=True)
        failed_unit(1, "WORD_RENDER_REQUIRED", "Word native parts remain available; a controlled render is required",
                    {"source_unit": "logical_document", "source_page_index": None, "source_page_number": None,
                     "rendered_page_number": None, "native_text": "\n".join(block["text"] for block in (word or {}).get("blocks", []) if block["type"] == "paragraph" and block.get("channel") == "current")})
        pdf_data = None
        record["expected_units"] = 1
        record["stages"].append({"stage": "inspect", "status": "failed"})

    if pdf_data is not None:
        try:
            reader = PdfReader(io.BytesIO(pdf_data))
            if reader.is_encrypted:
                record["review_status"] = "needs_password"
                record["expected_units"] = 0
                issue(0, "NEEDS_PASSWORD", "An authorized decrypted source is required", technical=True)
            else:
                count = len(reader.pages)
                if count > settings.knowledge_max_pdf_pages:
                    raise ValueError("PDF_PAGE_LIMIT")
                record["expected_units"] = count
                with fitz.open(stream=pdf_data, filetype="pdf") as pdf:
                    if len(pdf) != count:
                        raise ValueError("PDF_PAGE_COUNT_CONFLICT")
                    labels = reader.page_labels
                    for index in range(count):
                        number = index + 1
                        cached = checkpoints.get(number)
                        if (suffix == "pdf" and cached and cached[0].get("config_sha256") == config_hash
                                and hashlib.sha256(cached[1]).hexdigest() == cached[0].get("image_sha256")
                                and resumable(cached[0], cached[2])):
                            await process(number, cached[1], "", {})
                            continue
                        try:
                            native_page = pdf[index]
                            area = native_page.rect.width * native_page.rect.height
                            if area <= 0:
                                raise ValueError("PDF_PAGE_GEOMETRY")
                            scale = min(settings.extraction_render_dpi / 72, (settings.extraction_max_image_pixels / area) ** 0.5)
                            # Native rendering stays on one process/thread; worker processes provide concurrency.
                            image = native_page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes("png")
                            details = native_pdf(native_page, scale)
                            details["source_unit"] = "pdf_page"
                            details["pdf_page_label"] = labels[index] if index < len(labels) else None
                            if suffix == "docx":
                                details.update({"source_unit": "word_rendered_page", "source_page_index": None, "source_page_number": None})
                            try:
                                native = reader.pages[index].extract_text() or ""
                            except Exception:
                                native = native_page.get_text()
                                issue(number, "NATIVE_PARSER_FALLBACK", "pypdf text failed; the PyMuPDF source candidate is retained")
                        except Exception as exc:
                            failed_unit(number, "PDF_PAGE_FAILED", f"Native extraction or rendering failed ({type(exc).__name__})")
                            continue
                        await process(number, image, native, details, verify_cached_image=suffix == "docx")
        except Exception as exc:
            # Storage/checkpoint failures must remain retryable rather than become source approvals.
            if isinstance(exc, (CheckpointWriteError, ConnectionError, TimeoutError)):
                raise
            issue(0, "PDF_PARSE_FAILED", f"PDF inspection failed ({type(exc).__name__})", technical=True)
            if not pages:
                record["expected_units"] = 0
    elif suffix in {"png", "jpg", "jpeg", "tif", "tiff"}:
        try:
            with Image.open(io.BytesIO(data)) as original:
                count = getattr(original, "n_frames", 1)
                if count > settings.knowledge_max_pdf_pages:
                    raise ValueError("IMAGE_FRAME_LIMIT")
                record["expected_units"] = count
                for index, frame in enumerate(ImageSequence.Iterator(original)):
                    if frame.width * frame.height > 100_000_000:
                        raise ValueError("IMAGE_PIXEL_LIMIT")
                    oriented = ImageOps.exif_transpose(frame).convert("RGB")
                    source_size = list(oriented.size)
                    scale = min(1.0, (settings.extraction_max_image_pixels / (oriented.width * oriented.height)) ** 0.5)
                    if scale < 1:
                        oriented = oriented.resize((max(1, int(oriented.width * scale)), max(1, int(oriented.height * scale))))
                    output = io.BytesIO()
                    oriented.save(output, format="PNG")
                    await process(index + 1, output.getvalue(), "", {"source_unit": "image_frame", "source_frame_index": index,
                                  "source_page_index": None, "source_page_number": None, "source_dimensions_px": source_size,
                                  "render_scale": scale, "orientation_policy": "EXIF_TRANSPOSE_RECORDED"}, verify_cached_image=True)
        except Exception as exc:
            if isinstance(exc, CheckpointWriteError):
                raise
            issue(0, "IMAGE_DECODE_FAILED", f"Image/frame decoding failed ({type(exc).__name__})", technical=True)
            record.setdefault("expected_units", len(pages) or 1)
    elif suffix in {"txt", "md", "markdown"}:
        record.update({"expected_units": 1, "vision_model": None, "vision_provider": None})
        try:
            pages.append(text_unit(data))
        except UnicodeDecodeError:
            issue(1, "ENCODING_REQUIRED", "Source bytes do not decode strictly; provide a correctly encoded source", technical=True)
            pages.append({"number": 1, "source_unit": "bytes", "source_page_index": None, "source_page_number": None,
                          "rendered_page_number": None, "native_text": "", "selected_text": None, "visual_text": None,
                          "image": None, "requires_image": False, "blocks": [], "inventory_complete": False})

    record.setdefault("expected_units", len(pages))
    for number in range(len(pages) + 1, record["expected_units"] + 1):
        failed_unit(number, "SOURCE_UNIT_NOT_PROCESSED", "This source unit was not processed after an earlier failure")
    if word and pdf_data is not None:
        for block in word["blocks"]:
            if block.get("mapping_status") == "source_reviewed":
                continue
            if block.get("channel") != "current" or not block["text"].strip():
                block["mapping_status"] = "SEPARATE_SOURCE_CHANNEL"
                continue
            matched = [page["number"] for page in pages if reflow(block["text"]) in reflow(page.get("native_text", ""))]
            block["rendered_pages"] = matched
            block["mapping_status"] = "matched" if len(matched) == 1 else "ambiguous"
            if block["part"] == "word/document.xml" and len(matched) != 1:
                issue(0, "WORD_MAPPING_AMBIGUOUS", f"Logical Word block {block['id']} needs an explicit rendered-page mapping")
    for page in pages:
        for block in page.get("blocks", []):
            structure = block.get("reviewed_structure") or block.get("visual") or {}
            if structure.get("continues_from_previous") or structure.get("continues_on_next"):
                if not block.get("related_block_ids"):
                    issue(page["number"], "CONTINUITY_REVIEW", "Link source fragments across pages explicitly", block["id"])
    if sum(len(page.get("native_text", "")) + len(page.get("visual_text") or "") for page in pages) > settings.knowledge_max_extracted_characters:
        issue(0, "TEXT_LIMIT", "Source text exceeds the configured limit", technical=True)
    visual_pages = [page for page in pages if page.get("requires_image")]
    record["stages"].extend([
        {"stage": "native_extract", "status": "not_applicable" if suffix in {"png", "jpg", "jpeg", "tif", "tiff"} else "failed" if any(i.get("technical") and i["code"] in {"PDF_PAGE_FAILED", "PDF_PARSE_FAILED", "ENCODING_REQUIRED", "WORD_RENDER_REQUIRED", "NEEDS_PASSWORD"} for i in issues) else "complete"},
        {"stage": "render", "status": "not_applicable" if not visual_pages else "complete" if all(page.get("image") in artifacts for page in visual_pages) else "failed"},
        {"stage": "visual_inventory", "status": "not_applicable" if not visual_pages else "complete" if all(page.get("inventory_complete") for page in visual_pages) else "failed"},
        {"stage": "region_reading", "status": "not_applicable" if not visual_pages else "complete" if all(resumable(page, [i for i in issues if i["page"] == page["number"]]) for page in visual_pages) else "failed"},
        {"stage": "reconcile", "status": "needs_review" if any(i.get("status") != "resolved" for i in issues) else "complete"},
        {"stage": "human_review", "status": "pending"},
    ])
    package = ExtractionPackage(record, artifacts)
    package.refresh()
    return package


def reflow(text: str) -> str:
    return " ".join(text.split())
