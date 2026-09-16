"""Source-preserving hybrid extraction with bounded NVIDIA reading and review gates."""
from __future__ import annotations

import asyncio
import codecs
import hashlib
import io
import json
import re
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any

import fitz
from PIL import Image, ImageOps, ImageSequence
from pypdf import PdfReader

from northstar_api.config import Settings
from northstar_api.services.extraction_regions import PROMPT_VERSION, crop_image, read_page, region_artifacts
from northstar_api.services.extraction_schema import digest
from northstar_api.services.extraction_validation import critical_page, disagreement, metrics, same_text, validate
from northstar_api.services.extraction_word import inspect_word, render_word
from northstar_api.services.vision import read_image

PageCheckpoint = tuple[dict[str, Any], bytes, list[dict[str, Any]]]
PageCallback = Callable[[dict[str, Any], bytes, list[dict[str, Any]]], Awaitable[None]]


def configuration(settings: Settings) -> dict[str, Any]:
    return {key: value for key, value in settings.model_dump().items() if key.startswith('extraction_')}


@dataclass
class ExtractionPackage:
    record: dict[str, Any]
    images: dict[str, bytes]

    @property
    def issues(self) -> list[dict[str, Any]]:
        return self.record['issues']

    def refresh(self) -> None:
        self.record['checks'] = validate(self.record, self.images)
        self.record['metrics'] = metrics(self.record)
        passed = all(check['status'] == 'PASSED' for check in self.record['checks'])
        self.record['release_eligible'] = passed
        if self.record['review_status'] == 'verified_release' and not passed:
            self.record['review_status'] = 'needs_review'
        self.record['release_blockers'] = [c['name'] for c in self.record['checks'] if c['status'] != 'PASSED']

    def review_text(self) -> str:
        self.refresh()
        lines = [f"SOURCE SHA-256: {self.record['source_sha256']}",
                 f"STATUS: {self.record['review_status'].upper()}",
                 'Source strings are JSON-escaped to preserve newlines, delimiters and exact characters.']
        for page in self.record['pages']:
            lines.extend([f"SOURCE UNIT: {page['number']} ({page.get('source_unit', 'page')})",
                          f"PRINTED PAGE LABEL: {json.dumps(page.get('printed_page_label'), ensure_ascii=False)}",
                          f"IMAGE: {page.get('image') or 'NONE'}"])
            for key in ('native_text', 'visual_text', 'selected_text'):
                lines.append(f"{key.upper()}: {json.dumps(page.get(key), ensure_ascii=False)}")
            for block in page.get('blocks', []):
                lines.append(f"[{block['type'].upper()} {block['id']}] " + json.dumps(block, ensure_ascii=False, sort_keys=True))
        for issue in self.issues:
            lines.append('[ISSUE - NOT SOURCE TEXT] ' + json.dumps(issue, ensure_ascii=False, sort_keys=True))
        # A lossless tagged record is checked against extracted.json before every export.
        lines.append('CANONICAL_RECORD\t' + json.dumps(self.record, ensure_ascii=False, sort_keys=True))
        return '\n'.join(lines) + '\n'

    def validation_text(self) -> str:
        self.refresh()
        lines = [f"Source SHA-256: {self.record['source_sha256']}",
                 f"Extraction revision: {self.record.get('extraction_revision')}",
                 f"Configuration SHA-256: {self.record.get('config_sha256')}",
                 f"Expected units: {self.record['expected_units']}",
                 f"Processed units: {len(self.record['pages'])}",
                 f"Vision model: {self.record.get('vision_model') or 'NOT_RUN'}",
                 'Measured accuracy: NOT_MEASURED',
                 f"Verified release: {'APPROVED' if self.record['review_status'] == 'verified_release' and self.record['release_eligible'] else 'BLOCKED'}"]
        for check in self.record['checks']:
            lines.append(f"{check['name']}: {check['status']} " + json.dumps(check['details'], ensure_ascii=False))
        for issue in self.issues:
            lines.append(json.dumps(issue, sort_keys=True, ensure_ascii=False))
        return '\n'.join(lines) + '\n'

    def archive(self) -> bytes:
        self.refresh()
        report = self.review_text().encode('utf-8')
        validation = self.validation_text().encode('utf-8')
        canonical = json.dumps(self.record, ensure_ascii=False, sort_keys=True, indent=2).encode('utf-8')
        tagged = [line[len('CANONICAL_RECORD\t'):] for line in report.decode().splitlines() if line.startswith('CANONICAL_RECORD\t')]
        if len(tagged) != 1 or json.loads(tagged[0]) != json.loads(canonical):
            raise ValueError('Export projection differs from canonical records')
        artifacts = {'extracted.json': canonical, 'extracted_review.txt': report,
                     'validation_report.txt': validation,
                     'correction_history.json': json.dumps(self.record.get('correction_history', []), ensure_ascii=False, sort_keys=True).encode(),
                     **self.images}
        manifest = {'schema_version': 2, 'extraction_revision': self.record.get('extraction_revision'),
                    'source_sha256': self.record['source_sha256'], 'prompt_version': PROMPT_VERSION,
                    'config_sha256': self.record.get('config_sha256'), 'parsers': self.record.get('parsers'),
                    'vision_model': self.record.get('vision_model'), 'vision_provider': self.record.get('vision_provider'),
                    'expected_units': self.record['expected_units'],
                    'artifacts': {name: hashlib.sha256(data).hexdigest() for name, data in artifacts.items()}}
        artifacts['manifest.json'] = json.dumps(manifest, sort_keys=True, indent=2).encode()
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(artifacts.items()):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, data)
        return output.getvalue()


def encode_page_checkpoint(
    page: dict[str, Any],
    image: bytes,
    page_issues: list[dict[str, Any]],
    *,
    source_sha256: str,
    model: str,
    version: int,
) -> bytes:
    metadata = {
        "source_sha256": source_sha256,
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "version": version,
        "page": page,
        "issues": page_issues,
        "image_sha256": hashlib.sha256(image).hexdigest(),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("page.json", json.dumps(metadata, ensure_ascii=False, sort_keys=True))
        archive.writestr("image.png", image)
    return output.getvalue()


def decode_page_checkpoint(
    data: bytes,
    *,
    source_sha256: str,
    model: str,
    version: int,
    page_number: int,
) -> PageCheckpoint:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if set(archive.namelist()) != {"page.json", "image.png"}:
            raise ValueError("Checkpoint artifact set is invalid")
        metadata = json.loads(archive.read("page.json"))
        image = archive.read("image.png")
    page = metadata.get("page")
    if (
        metadata.get("source_sha256") != source_sha256
        or metadata.get("model") != model
        or metadata.get("prompt_version") != PROMPT_VERSION
        or metadata.get("version") != version
        or not isinstance(page, dict)
        or page.get("number") != page_number
        or metadata.get("image_sha256") != hashlib.sha256(image).hexdigest()
        or page.get("image_sha256") != hashlib.sha256(image).hexdigest()
        or not isinstance(metadata.get("issues"), list)
    ):
        raise ValueError("Checkpoint source identity or checksum failed")
    return page, image, metadata["issues"]



def _compare(native: str, visual: str) -> bool:
    return same_text(native, visual)


async def _read_image(image: bytes, settings: Settings) -> str:
    return await read_image(image, settings)


def text_unit(data: bytes) -> dict[str, Any]:
    encoding, bom = 'utf-8', b''
    for marker, codec in [(codecs.BOM_UTF32_LE, 'utf-32-le'), (codecs.BOM_UTF32_BE, 'utf-32-be'),
                          (codecs.BOM_UTF8, 'utf-8'), (codecs.BOM_UTF16_LE, 'utf-16-le'), (codecs.BOM_UTF16_BE, 'utf-16-be')]:
        if data.startswith(marker):
            encoding, bom = codec, marker
            break
    text = data[len(bom):].decode(encoding, errors='strict')
    offset = len(bom)
    lines = []
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        size = len(line.encode(encoding))
        lines.append({'number': number, 'byte_start': offset, 'byte_end': offset + size, 'text': line})
        offset += size
    endings = re.findall(r'\r\n|\r|\n', text)
    return {'number': 1, 'source_page_index': None, 'source_page_number': None,
            'rendered_page_number': None, 'source_unit': 'bytes', 'native_text': text,
            'visual_text': None, 'selected_text': text, 'image': None, 'requires_image': False,
            'encoding': encoding, 'bom_hex': bom.hex(), 'line_endings': sorted(set(endings)),
            'lines': lines, 'line_byte_offsets': [line['byte_start'] for line in lines], 'blocks': [],
            'blank': not text, 'inventory_complete': True}


def native_pdf(page: Any, scale: float) -> dict[str, Any]:
    blocks = []
    words = []
    def box(value: Any) -> list[int]:
        rect = fitz.Rect(value) * page.rotation_matrix
        return [max(0, round(v * scale)) for v in rect]
    for i, value in enumerate(page.get_text('dict')['blocks']):
        if value['type'] == 0:
            spans = [span for line in value['lines'] for span in line['spans']]
            blocks.append({'id': f'N{i:04d}', 'type': 'text', 'bbox_pt': list(value['bbox']),
                           'bbox_px': box(value['bbox']), 'text': '\n'.join(''.join(s['text'] for s in line['spans']) for line in value['lines']),
                           'spans': spans})
        else:
            blocks.append({'id': f'N{i:04d}', 'type': 'figure', 'bbox_pt': list(value['bbox']),
                           'bbox_px': box(value['bbox']), 'text': '', 'image_sha256': hashlib.sha256(value.get('image', b'')).hexdigest()})
    for word in page.get_text('words'):
        words.append({'bbox_px': box(word[:4]), 'text': word[4], 'line': [word[5], word[6]]})
    tables = []
    try:
        for table in page.find_tables().tables:
            tables.append({'bbox_px': box(table.bbox), 'row_count': table.row_count,
                           'column_count': table.col_count, 'rows': table.extract(),
                           'cell_bboxes_pt': table.cells, 'header': table.header.names})
        table_error = None
    except Exception as exc:
        table_error = type(exc).__name__
    annotations = [{'type': a.type, 'rect': list(a.rect), 'info': a.info} for a in page.annots() or []]
    widgets = [{'name': w.field_name, 'value': w.field_value, 'rect': list(w.rect)} for w in page.widgets() or []]
    return {'native_blocks': blocks, 'native_words': words, 'native_tables': tables,
            'native_table_error': table_error, 'annotations': annotations, 'form_fields': widgets,
            'rotation': page.rotation, 'source_width_pt': page.rect.width,
            'source_height_pt': page.rect.height, 'render_scale': scale}


def inside(inner: list[float], outer: list[float]) -> bool:
    return outer[0] <= (inner[0] + inner[2]) / 2 <= outer[2] and outer[1] <= (inner[1] + inner[3]) / 2 <= outer[3]


async def extract_document(data: bytes, filename: str, settings: Settings, *,
                           resume_pages: dict[int, PageCheckpoint] | None = None,
                           on_page: PageCallback | None = None) -> ExtractionPackage:
    suffix = filename.lower().rsplit('.', 1)[-1]
    if len(data) > settings.upload_max_bytes:
        raise ValueError('Source exceeds upload size limit')
    source_hash = hashlib.sha256(data).hexdigest()
    pages: list[dict[str, Any]] = []
    artifacts: dict[str, bytes] = {f'source/original.{suffix}': data}
    issues: list[dict[str, Any]] = []
    resume_pages = resume_pages or {}
    config = configuration(settings)
    record: dict[str, Any] = {'schema_version': 2, 'extraction_revision': None, 'source_name': filename,
        'source_sha256': source_hash, 'config': config, 'config_sha256': digest(config),
        'pages': pages, 'issues': issues, 'vision_model': settings.extraction_vision_model,
        'vision_provider': 'nvidia', 'review_status': 'needs_review', 'approved_pages': [],
        'correction_history': [], 'stages': [],
        'parsers': {name: version(name) for name in ('pymupdf', 'pypdf', 'python-docx', 'pillow', 'langchain-nvidia-ai-endpoints')}}

    def issue(number: int, code: str, message: str, block_id: str | None = None, technical: bool = False) -> None:
        issues.append({'id': f'I{len(issues) + 1:06d}', 'page': number, 'code': code, 'message': message,
                       'block_id': block_id, 'technical': technical, 'status': 'open',
                       'severity': 'CRITICAL' if technical or code in {'NUMERIC_CONFLICT', 'CRITICAL_WORD_CONFLICT'} else 'REVIEW'})

    async def process(number: int, image: bytes, native: str, details: dict[str, Any]) -> None:
        start = len(issues)
        if number in resume_pages:
            saved, saved_image, saved_issues = resume_pages[number]
            if saved.get('config_sha256') != record['config_sha256']:
                raise ValueError('Checkpoint configuration changed; retry as a new extraction revision')
            page = saved
            image = saved_image
            for value in saved_issues:
                issues.append({**value, 'id': f'I{len(issues) + 1:06d}'})
        else:
            with Image.open(io.BytesIO(image)) as bitmap:
                width, height = bitmap.size
            page = {'number': number, 'source_page_index': number - 1, 'source_page_number': number,
                    'rendered_page_number': number, 'printed_page_label': None,
                    'source_unit': 'page', 'native_text': native, 'image': f'pages/page_{number:04d}.png',
                    'image_sha256': hashlib.sha256(image).hexdigest(), 'width_px': width, 'height_px': height,
                    'requires_image': True, 'selected_text': None, 'config_sha256': record['config_sha256'], **details}
            visual = await read_page(image, number, settings)
            for problem in visual.pop('problems'):
                issue(number, **problem)
            page.update(visual)
            leaves = [b for b in page['blocks'] if b['status'] != 'split']
            for block in leaves:
                selected_words = [w for w in page.get('native_words', []) if inside(w['bbox_px'], block['bbox_px'])]
                block['native_text'] = ' '.join(w['text'] for w in selected_words)
                reading = block.get('visual')
                if reading:
                    block['agreement'] = bool(block['native_text']) and same_text(block['native_text'], reading['text'])
                    if block['agreement']:
                        block['selected_text'] = reading['text']
                    elif block['native_text']:
                        issue(number, disagreement(block['native_text'], reading['text']), 'Native and visual region candidates differ', block['id'])
                block['requires_second_review'] = block['type'] in {'table', 'equation', 'question', 'answer_key'}
            for native_block in page.get('native_blocks', []):
                if not any(inside(native_block['bbox_px'], b['bbox_px']) for b in leaves):
                    issue(number, 'NATIVE_REGION_UNACCOUNTED', f"Native object {native_block['id']} is absent from the visual inventory")
            if native and not same_text(native, page['visual_text']):
                issue(number, disagreement(native, page['visual_text']), 'Whole-page native and visual transcripts disagree; inspect reading order and coverage')
            if page.get('native_table_error'):
                issue(number, 'NATIVE_TABLE_CHECK_FAILED', 'Native table inspection failed; inspect all table structures')
            for table in page.get('native_tables', []):
                candidates = [b for b in leaves if b['type'] == 'table' and inside(table['bbox_px'], b['bbox_px'])]
                if not candidates:
                    issue(number, 'TABLE_STRUCTURE_UNKNOWN', 'Native table has no matching visual table')
                else:
                    cells = (candidates[0].get('visual') or {}).get('cells', [])
                    for r, row in enumerate(table['rows']):
                        for c, value in enumerate(row):
                            if value is not None and not any(cell['row'] == r and cell['column'] == c and same_text(value, cell['text']) for cell in cells):
                                issue(number, 'TABLE_CELL_CONFLICT', f'Native table cell row {r + 1}, column {c + 1} differs from visual cell', candidates[0]['id'])
            for i, left in enumerate(leaves):
                for right in leaves[i + 1:]:
                    a, b = left['bbox_px'], right['bbox_px']
                    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
                    if overlap > 0.1 * min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])):
                        issue(number, 'REGION_OVERLAP', f"Visual regions {left['id']} and {right['id']} overlap")
            if leaves and all(b.get('selected_text') is not None for b in leaves):
                page['selected_text'] = '\n'.join(b['selected_text'] for b in leaves)
            elif page.get('blank') and not native:
                page['selected_text'] = ''
            page['requires_second_review'] = critical_page(page)
            if not issues[start:]:
                issue(number, 'SOURCE_REVIEW_REQUIRED', 'Compare all source content and region boundaries before approval')
        pages.append(page)
        artifacts[page['image']] = image
        artifacts.update(region_artifacts(page, image))
        if on_page:
            await on_page(page, image, issues[start:])

    record['stages'].append({'stage': 'inspect', 'status': 'complete'})
    word = None
    if suffix == 'docx':
        word, derivative = inspect_word(data, settings)
        record['word'] = word
        artifacts['derivatives/frozen.docx'] = derivative
        try:
            if word['render_blockers']:
                raise ValueError('WORD_UNSAFE_RENDER_DEPENDENCY')
            rendered_data, renderer = await asyncio.to_thread(render_word, derivative, settings)
            record['word']['renderer'] = renderer
            artifacts['derivatives/rendered.pdf'] = rendered_data
            pdf_data = rendered_data
        except Exception as exc:
            issue(1, 'WORD_RENDER_REQUIRED', f'Controlled Word rendering unavailable ({type(exc).__name__})', technical=True)
            native = '\n'.join(b['text'] for b in word['blocks'] if b['part'] == 'word/document.xml' and b['type'] == 'paragraph')
            pages.append({'number': 1, 'source_page_number': None, 'source_page_index': None, 'rendered_page_number': None,
                          'source_unit': 'logical_document', 'native_text': native, 'visual_text': None,
                          'selected_text': None, 'requires_image': True, 'image': None, 'blocks': [], 'inventory_complete': False})
            pdf_data = None
    elif suffix == 'pdf':
        pdf_data = data
    else:
        pdf_data = None
    if pdf_data is not None:
        reader = PdfReader(io.BytesIO(pdf_data))
        if reader.is_encrypted:
            record['review_status'] = 'needs_password'
            record['expected_units'] = 0
            issue(0, 'NEEDS_PASSWORD', 'Supply a source unlocked with its password', technical=True)
        else:
            count = len(reader.pages)
            if count > settings.knowledge_max_pdf_pages:
                raise ValueError('Source exceeds the configured page limit')
            record['expected_units'] = count
            with fitz.open(stream=pdf_data, filetype='pdf') as document:
                if len(document) != count:
                    raise ValueError('PDF parsers disagree about page count')
                labels = reader.page_labels
                for index, page in enumerate(document):
                    number = index + 1
                    if number in resume_pages:
                        await process(number, resume_pages[number][1], '', {})
                        continue
                    if sum(map(len, artifacts.values())) > settings.extraction_max_evidence_bytes:
                        issue(number, 'EVIDENCE_LIMIT', 'Configured evidence size limit reached', technical=True)
                        pages.append({'number': number, 'native_text': '', 'visual_text': None, 'selected_text': None,
                                      'image': None, 'requires_image': True, 'blocks': [], 'inventory_complete': False})
                        continue
                    scale = min(settings.extraction_render_dpi / 72, (settings.extraction_max_image_pixels / max(1, page.rect.width * page.rect.height)) ** 0.5)
                    image = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes('png')
                    native = reader.pages[index].extract_text() or ''
                    details = native_pdf(page, scale)
                    details['pdf_page_label'] = labels[index] if index < len(labels) else None
                    details['source_unit'] = 'word_rendered_page' if word else 'pdf_page'
                    await process(number, image, native, details)
    elif suffix in {'png', 'jpg', 'jpeg', 'tif', 'tiff'}:
        with Image.open(io.BytesIO(data)) as original:
            count = getattr(original, 'n_frames', 1)
            if count > settings.knowledge_max_pdf_pages:
                raise ValueError('Image source exceeds frame limit')
            record['expected_units'] = count
            for index, frame in enumerate(ImageSequence.Iterator(original)):
                if frame.width * frame.height > 100_000_000:
                    raise ValueError('Image source exceeds pixel limit')
                oriented = ImageOps.exif_transpose(frame).convert('RGB')
                original_size = list(oriented.size)
                ratio = min(1.0, (settings.extraction_max_image_pixels / (oriented.width * oriented.height)) ** 0.5)
                if ratio < 1:
                    oriented = oriented.resize((max(1, round(oriented.width * ratio)), max(1, round(oriented.height * ratio))))
                output = io.BytesIO()
                oriented.save(output, format='PNG')
                await process(index + 1, output.getvalue(), '', {'source_unit': 'image_frame',
                              'source_frame_index': index, 'original_dimensions_px': original_size,
                              'exif_orientation_applied': True, 'render_scale': ratio})
    elif suffix in {'txt', 'md', 'markdown'}:
        record['expected_units'] = 1
        record['vision_model'] = None
        record['vision_provider'] = None
        try:
            pages.append(text_unit(data))
        except UnicodeDecodeError:
            issue(1, 'ENCODING_REQUIRED', 'Strict decoding failed; supply a UTF-8 or BOM-labelled UTF-16/32 source', technical=True)
            pages.append({'number': 1, 'source_unit': 'bytes', 'native_text': '', 'visual_text': None,
                          'selected_text': None, 'requires_image': False, 'image': None, 'blocks': []})
    elif suffix != 'docx':
        raise ValueError('Unsupported source extension')
    record.setdefault('expected_units', len(pages))
    if word and pdf_data:
        for block in word['blocks']:
            text = re.sub(r'\s+', ' ', block['text']).strip()
            matches = [p['number'] for p in pages if text and text in re.sub(r'\s+', ' ', p['native_text'])]
            block['rendered_pages'] = matches
            block['mapping_status'] = 'matched' if len(matches) == 1 else 'ambiguous'
            if block['part'] == 'word/document.xml' and block['type'] == 'paragraph' and text and len(matches) != 1:
                issue(matches[0] if matches else 1, 'WORD_MAPPING_AMBIGUOUS', f"Logical block {block['id']} needs source-to-page mapping review")
    for page in pages:
        for block in page.get('blocks', []):
            reading = block.get('visual') or {}
            if reading.get('continues_from_previous') or reading.get('continues_on_next'):
                issue(page['number'], 'CONTINUITY_REVIEW', 'Confirm the linked source fragments across pages', block['id'])
    if sum(len(p.get('native_text', '')) + len(p.get('visual_text') or '') for p in pages) > settings.knowledge_max_extracted_characters:
        issue(0, 'TEXT_LIMIT', 'Extracted candidates exceed configured text limit', technical=True)
    record['stages'].extend([{'stage': name, 'status': 'complete'} for name in ('native_extract', 'render', 'visual_inventory', 'region_reading', 'reconcile')])
    record['stages'].append({'stage': 'human_review', 'status': 'pending'})
    package = ExtractionPackage(record, artifacts)
    package.refresh()
    return package
