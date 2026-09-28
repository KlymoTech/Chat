import { describe, expect, it } from 'vitest';
import { replaceWords, targetFor } from '@/components/extraction-area-placement';
import type { ExtractionBlock, ExtractionPage } from '@/lib/api';

const paragraph: ExtractionBlock = {
  id: 'P0001-R0001', type: 'paragraph', status: 'candidate', native_text: 'The site has 600 m2 of area.',
  selected_text: 'The site has\n600 m2 of area.', visual: null, consensus: 'native_ocr', bbox_px: [100, 100, 700, 200],
};
const table: ExtractionBlock = {
  id: 'P0001-R0002', type: 'table', status: 'candidate', native_text: 'Zone Water A1 960', selected_text: null, visual: null,
  bbox_px: [100, 300, 900, 420],
  proposed_structure: { kind: 'table', text: '', complete: true, cells: [
    { row: 0, column: 0, text: 'Zone', header: true }, { row: 0, column: 1, text: 'Water', header: true },
    { row: 1, column: 0, text: 'A1' }, { row: 1, column: 1, text: '960' }] },
  native_table: { rows: 2, columns: 2, column_bounds: [[110, 300], [700, 890]], row_bounds: [[310, 340], [370, 400]], bbox_px: [110, 310, 890, 400] },
};
const words = [['The', 110], ['site', 170], ['has', 240], ['600', 110], ['m2', 170], ['of', 240], ['area.', 300]]
  .map(([text, x], i) => ({ text: text as string, bbox_px: [x as number, i < 3 ? 110 : 160, (x as number) + 50, i < 3 ? 140 : 190] }));
const page: ExtractionPage = {
  number: 1, native_text: '', visual_text: null, selected_text: null, image: 'p', width_px: 1000, height_px: 1400,
  blocks: [paragraph, table], native_words: words,
};

describe('Area placement', () => {
  it('targets exactly the words inside the box and keeps the rest of the text', () => {
    const target = targetFor(page, [100, 150, 230, 200], {});
    expect(target).toMatchObject({ mode: 'part', start: 3, end: 4, selected: '600 m2' });
    expect(replaceWords('The site has\n600 m2 of area.', 3, 4, '600 m²')).toBe('The site has\n600 m² of area.');
  });

  it('targets the whole region when the box covers all of it', () => {
    expect(targetFor(page, [90, 90, 710, 210], {})).toMatchObject({ mode: 'whole', block: { id: 'P0001-R0001' } });
  });

  it('targets the table cells the box covers', () => {
    const target = targetFor(page, [690, 360, 900, 410], {});
    expect(target.mode).toBe('cells');
    expect(target.mode === 'cells' && target.cells.map((c) => [c.row, c.column, c.text])).toEqual([[1, 1, '960']]);
  });

  it('reports when a box is outside every region', () => {
    expect(targetFor(page, [0, 1300, 50, 1390], {})).toEqual({ mode: 'none' });
  });

  it('falls back to the whole region once its text was edited by hand', () => {
    const edited = { 'P0001-R0001': { kind: 'paragraph', text: 'Rewritten by a reviewer', complete: true } };
    expect(targetFor(page, [100, 150, 230, 200], edited)).toMatchObject({ mode: 'whole' });
  });
});
