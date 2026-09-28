import type { ExtractionBlock, ExtractionPage, ExtractionReading, ExtractionWord } from '@/lib/api';
import { finalText } from '@/components/extraction-layout-view';

/** Where an area extraction goes: some table cells, some words of a region, or a whole region. */
export type AreaTarget =
  | { mode: 'cells'; block: ExtractionBlock; cells: Array<{ row: number; column: number; bbox_px: number[]; text: string }>; others: number }
  | { mode: 'part'; block: ExtractionBlock; start: number; end: number; selected: string; others: number }
  | { mode: 'whole'; block: ExtractionBlock; others: number }
  | { mode: 'none' };

type Box = [number, number, number, number];
const overlap = (a: number[], b: number[]) =>
  Math.max(0, Math.min(a[2]!, b[2]!) - Math.max(a[0]!, b[0]!)) * Math.max(0, Math.min(a[3]!, b[3]!) - Math.max(a[1]!, b[1]!));
const area = (a: number[]) => Math.max(0, a[2]! - a[0]!) * Math.max(0, a[3]! - a[1]!);
const centerIn = (inner: number[], outer: number[]) => {
  const cx = (inner[0]! + inner[2]!) / 2; const cy = (inner[1]! + inner[3]!) / 2;
  return outer[0]! <= cx && cx <= outer[2]! && outer[1]! <= cy && cy <= outer[3]!;
};
const normalize = (value: string) => value.normalize('NFKC').replace(/\s+/g, ' ').trim();

/** The source words that spell a region's current text, in order (null once it has been edited). */
export function regionWords(page: ExtractionPage, block: ExtractionBlock, text: string): ExtractionWord[] | null {
  for (const pool of [page.native_words, page.ocr_words]) {
    const words = (pool ?? []).filter((w) => block.bbox_px && centerIn(w.bbox_px, block.bbox_px));
    if (words.length && normalize(words.map((w) => w.text).join(' ')) === normalize(text)) return words;
  }
  return null;
}

/** Cell boxes of a table region, from the column and row bounds found in the source. */
export function tableCellBoxes(block: ExtractionBlock, draft: ExtractionReading | null) {
  const table = block.native_table;
  const cells = draft?.cells?.length ? draft.cells : (block.proposed_structure?.cells ?? []);
  if (!table) return [];
  return cells.map((cell) => {
    const columns = table.column_bounds.slice(cell.column, cell.column + (cell.column_span ?? 1));
    const rows = table.row_bounds[cell.row];
    if (!columns.length || !rows) return null;
    return { row: cell.row, column: cell.column, text: cell.text,
      bbox_px: [columns[0]![0]!, rows[0]!, columns[columns.length - 1]![1]!, rows[1]!] as Box };
  }).filter((c): c is NonNullable<typeof c> => c !== null);
}

export function targetFor(page: ExtractionPage, box: number[], drafts: Record<string, ExtractionReading | null>): AreaTarget {
  const leaves = (page.blocks ?? []).filter((b) => b.status !== 'split' && b.bbox_px);
  const ranked = leaves.map((block) => ({ block, share: overlap(box, block.bbox_px!) / Math.max(1, Math.min(area(box), area(block.bbox_px!))) }))
    .filter((r) => r.share > 0.05).sort((a, b) => b.share - a.share);
  const best = ranked[0];
  if (!best) return { mode: 'none' };
  const { block } = best;
  const others = ranked.length - 1;
  const draft = drafts[block.id] ?? null;
  const cellBoxes = tableCellBoxes(block, draft);
  if (cellBoxes.length) {
    // A cell is selected when most of it lies inside the box.
    const cells = cellBoxes.filter((c) => overlap(box, c.bbox_px) >= 0.5 * area(c.bbox_px) || centerIn(c.bbox_px, box));
    return cells.length ? { mode: 'cells', block, cells, others } : { mode: 'whole', block, others };
  }
  const text = finalText(block, draft);
  const words = regionWords(page, block, text);
  if (!words) return { mode: 'whole', block, others };
  const chosen = words.map((w, i) => (centerIn(w.bbox_px, box) ? i : -1)).filter((i) => i >= 0);
  if (!chosen.length || chosen.length === words.length) return { mode: 'whole', block, others };
  const start = chosen[0]!; const end = chosen[chosen.length - 1]!;
  return { mode: 'part', block, start, end, selected: words.slice(start, end + 1).map((w) => w.text).join(' '), others };
}

/** Replace words start..end (inclusive) of ``text`` with ``replacement``, keeping every other
 * character — spacing and line breaks — exactly as it was. */
export function replaceWords(text: string, start: number, end: number, replacement: string): string {
  const tokens = text.split(/(\s+)/);
  let index = -1; let first = -1; let last = -1;
  tokens.forEach((token, i) => {
    if (!token || /^\s+$/.test(token)) return;
    index += 1;
    if (index === start) first = i;
    if (index === end) last = i;
  });
  if (first < 0 || last < 0) return text;
  return [...tokens.slice(0, first), replacement, ...tokens.slice(last + 1)].join('');
}
