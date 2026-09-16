"""Ground-truth scoring and an explicit live probe; neither runs during ingestion."""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import secrets
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from northstar_api.services.extraction_evidence import leaf_blocks, sha256, source_tokens
from northstar_api.services.extraction_schema import digest, strict_json


def edit_distance(expected: list[str] | str, actual: list[str] | str) -> int | None:
    """Exact Levenshtein distance, with an explicit work limit rather than a guess."""
    if len(expected) * len(actual) > 5_000_000:
        return None
    previous = list(range(len(actual) + 1))
    for i, left in enumerate(expected, 1):
        current = [i]
        for j, right in enumerate(actual, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (left != right)))
        previous = current
    return previous[-1]


def evaluate(record: dict[str, Any], gold: dict[str, Any]) -> dict[str, Any]:
    """Gold: human_adjudicated, adjudicator, source_sha256, canonical-style pages.

    Gold block IDs are source annotation IDs aligned to the candidate once by a
    human. Missing/unmatched IDs are errors, never silently removed from scoring.
    """
    if gold.get('human_adjudicated') is not True or not gold.get('adjudicator'):
        raise ValueError('A human-adjudicated ground truth and adjudicator are required')
    if gold.get('source_sha256') != record.get('source_sha256'):
        raise ValueError('Ground truth belongs to a different source')
    expected = {p['number']: p for p in gold['pages']}
    actual = {p['number']: p for p in record['pages']}
    if len(expected) != len(gold['pages']) or len(actual) != len(record['pages']):
        raise ValueError('Duplicate page identities cannot be benchmarked')
    totals = {'characters': 0, 'words': 0, 'character_errors': 0, 'word_errors': 0,
              'critical_token_errors': 0, 'blocks': 0, 'matched_blocks': 0,
              'table_cells': 0, 'exact_table_cells': 0, 'header_links': 0, 'exact_header_links': 0,
              'equations': 0, 'exact_equations': 0, 'questions': 0, 'exact_question_links': 0,
              'ordered_pages': 0, 'exact_reading_order_pages': 0}
    skipped: list[str] = []
    for number in sorted(expected.keys() | actual.keys()):
        page, candidate = expected.get(number, {}), actual.get(number, {})
        text, extracted = page.get('selected_text') or '', candidate.get('selected_text') or ''
        totals['characters'] += len(text); totals['words'] += len(text.split())
        for unit, left, right in [('character', text, extracted), ('word', text.split(), extracted.split())]:
            distance = edit_distance(left, right)
            if distance is None: skipped.append(f'{unit}_distance:page:{number}:work_limit')
            else: totals[f'{unit}_errors'] += distance
        left, right = Counter(source_tokens(text)), Counter(source_tokens(extracted))
        totals['critical_token_errors'] += sum((left - right).values()) + sum((right - left).values())
        blocks = leaf_blocks(page); found = {b['id']: b for b in leaf_blocks(candidate)}
        totals['ordered_pages'] += 1
        totals['exact_reading_order_pages'] += [b['id'] for b in blocks] == [b['id'] for b in leaf_blocks(candidate)]
        for block in blocks:
            totals['blocks'] += 1
            other = found.get(block['id'], {})
            totals['matched_blocks'] += bool(other)
            structure = block.get('reviewed_structure') or block.get('visual') or {}
            other_structure = other.get('reviewed_structure') or other.get('visual') or {}
            cells = {(c['row'], c['column']): c for c in other_structure.get('cells', [])}
            for cell in structure.get('cells', []):
                candidate_cell = cells.get((cell['row'], cell['column']), {})
                totals['table_cells'] += 1
                keys = ('text', 'state', 'row_span', 'column_span', 'unit')
                totals['exact_table_cells'] += bool(candidate_cell) and all(cell.get(k) == candidate_cell.get(k) for k in keys)
                totals['header_links'] += 1
                totals['exact_header_links'] += bool(candidate_cell) and cell.get('header_refs', []) == candidate_cell.get('header_refs', [])
            if structure.get('kind') == 'equation':
                totals['equations'] += 1
                totals['exact_equations'] += bool(other) and structure.get('latex') == other_structure.get('latex')
            if structure.get('kind') in {'question', 'answer_key'}:
                totals['questions'] += 1
                totals['exact_question_links'] += bool(other) and all(structure.get(k) == other_structure.get(k) for k in ('options', 'printed_answer', 'subparts')) and block.get('related_block_ids', []) == other.get('related_block_ids', [])
    def ratio(numerator: str, denominator: str) -> float | None:
        return totals[numerator] / totals[denominator] if totals[denominator] else None
    return {'status': 'PARTIALLY_MEASURED' if skipped else 'MEASURED_ON_SUPPLIED_GROUND_TRUTH',
            'source_sha256': record['source_sha256'], 'candidate_sha256': digest(record), 'ground_truth_sha256': digest(gold),
            'adjudicator': gold['adjudicator'], 'counts': totals, 'not_measured': skipped,
            'character_error_rate': None if any(s.startswith('character_') for s in skipped) else ratio('character_errors', 'characters'),
            'word_error_rate': None if any(s.startswith('word_') for s in skipped) else ratio('word_errors', 'words'),
            'block_recall': ratio('matched_blocks', 'blocks'), 'table_cell_exact_match': ratio('exact_table_cells', 'table_cells'),
            'header_association_exact_match': ratio('exact_header_links', 'header_links'),
            'equation_exact_match': ratio('exact_equations', 'equations'), 'question_answer_link_exact_match': ratio('exact_question_links', 'questions'),
            'reading_order_exact_match': ratio('exact_reading_order_pages', 'ordered_pages'),
            'missing_pages': sorted(expected.keys() - actual.keys()), 'unexpected_pages': sorted(actual.keys() - expected.keys()),
            'limitations': 'Scores describe supplied adjudicated cases, not universal accuracy. Human alignment of source IDs is required.'}


async def capability_probe(settings: Any) -> dict[str, Any]:
    """One explicit NVIDIA call; random source value is absent from the prompt."""
    from northstar_api.services.vision import read_evidence
    value = secrets.token_hex(6).upper()
    image = Image.new('RGB', (900, 160), 'white')
    ImageDraw.Draw(image).text((35, 45), value, fill='black', font=ImageFont.load_default(size=62))
    buffer = io.BytesIO(); image.save(buffer, format='PNG')
    response = await read_evidence(buffer.getvalue(), settings, 'Read the single printed alphanumeric value exactly. Return only that value; do not explain.')
    observed = response.get('raw')
    return {'test': 'image_only_random_value', 'status': 'PASSED' if response.get('finish_reason') == 'stop' and isinstance(observed, str) and observed.strip() == value else 'FAILED',
            'expected': value, 'observed': observed, 'image_sha256': sha256(buffer.getvalue()),
            'model': response.get('model'), 'finish_reason': response.get('finish_reason'),
            'limitations': 'Image input capability check only; this does not measure document extraction accuracy.'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path); parser.add_argument('--ground-truth', type=Path)
    parser.add_argument('--probe-nvidia', action='store_true'); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.probe_nvidia:
        if args.candidate or args.ground_truth: parser.error('Choose either probe or ground-truth evaluation')
        from northstar_api.config import get_settings
        result = asyncio.run(capability_probe(get_settings()))
    else:
        if not args.candidate or not args.ground_truth: parser.error('Both candidate and ground truth are required')
        result = evaluate(strict_json(args.candidate.read_bytes(), max_bytes=100_000_000), strict_json(args.ground_truth.read_bytes(), max_bytes=100_000_000))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(result['status'])
    if result['status'] == 'FAILED': raise SystemExit(1)


if __name__ == '__main__':
    main()
