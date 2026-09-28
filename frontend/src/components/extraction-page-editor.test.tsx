import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, waitFor } from '@testing-library/react';
import { createRef } from 'react';
import { Editor } from '@tiptap/core';
import type { Node as PMNode } from '@tiptap/pm/model';
import {
  ALLOW_STRUCTURE, PageEditor, editorExtensions, pageDocument, regionEdit, type PageEditorHandle,
} from '@/components/extraction-page-editor';
import type { ExtractionBlock, ExtractionPage } from '@/lib/api';

afterEach(cleanup);

const heading: ExtractionBlock = {
  id: 'P0001-R0001', type: 'heading', status: 'candidate', native_text: 'Crop allocation', selected_text: 'Crop allocation',
  visual: null, consensus: 'native_ocr', bbox_px: [100, 100, 700, 160],
  proposed_structure: { kind: 'heading', text: 'Crop allocation', complete: true },
  style: { font_size_px: 48, bold: true, italic: false, color: '#305f47', font: 'Helvetica-Bold', align: 'left' },
};
const table: ExtractionBlock = {
  id: 'P0001-R0002', type: 'table', status: 'candidate', native_text: 'Zone Water A1 960', selected_text: null, visual: null,
  bbox_px: [100, 200, 900, 400],
  proposed_structure: { kind: 'table', text: 'Zone | Water\nA1 | 960', complete: true, cells: [
    { row: 0, column: 0, text: 'Zone', header: true }, { row: 0, column: 1, text: 'Water', header: true },
    { row: 1, column: 0, text: 'A1', header_refs: ['R0C0'] }, { row: 1, column: 1, text: '960', header_refs: ['R0C1'] }] },
  native_table: { rows: 2, columns: 2, column_bounds: [[110, 300], [700, 890]], row_bounds: [[210, 250], [300, 340]], bbox_px: [110, 210, 890, 340] },
  cell_checks: [{ row: 1, column: 1, pdf: '960', ocr: '980', confirmed: false }],
};
const figure: ExtractionBlock = {
  id: 'P0001-R0003', type: 'figure', status: 'candidate', native_text: '', selected_text: null,
  visual: { kind: 'figure', text: 'Tank T-01', complete: true }, bbox_px: [100, 450, 900, 900],
  figure_description: 'A tank feeds a filter and a pump.',
};
const page: ExtractionPage = {
  number: 1, native_text: '', visual_text: null, selected_text: null, image: 'p.png', width_px: 1000, height_px: 1400,
  blocks: [heading, table, figure],
};

const editorFor = (value: ExtractionPage) => new Editor({ extensions: editorExtensions, content: pageDocument(value, {}, 'blob:page') });
const regions = (editor: Editor) => { const list: PMNode[] = []; editor.state.doc.forEach((n) => { list.push(n); }); return list; };

describe('Page editor document', () => {
  it('builds one document with every region in reading order, placed and styled like the source', () => {
    const editor = editorFor(page);
    expect(regions(editor).map((n) => [n.type.name, n.attrs.blockId])).toEqual([
      ['sourceText', 'P0001-R0001'], ['sourceTable', 'P0001-R0002'], ['sourceFigure', 'P0001-R0003']]);
    const title = regions(editor)[0]!;
    expect(title.attrs.left).toBe('10.0000%');
    expect(title.attrs.fontWeight).toBe('700');
    expect(title.attrs.color).toBe('#305f47');
    expect(title.attrs.fontSize).toBe('4.8000cqw'); // 48px on a 1000px-wide page
    editor.destroy();
  });

  it('renders tables as real tables with disputed cells marked', () => {
    const editor = editorFor(page);
    const html = editor.getHTML();
    expect(html).toContain('<th');
    expect(html).toMatch(/data-cell="1,1" class="xe-cell is-disputed"/);
    expect(html).toMatch(/data-cell="1,1"[^>]*text-align: ?right/); // numeric column
    editor.destroy();
  });

  it('reads edits back per region, with table cells and figure descriptions', () => {
    const editor = editorFor(page);
    const [, tableNode, figureNode] = regions(editor);
    const tableEdit = regionEdit(tableNode!, table, null);
    expect(tableEdit.text).toBe('Zone | Water\nA1 | 960');
    expect(tableEdit.cells?.find((c) => c.row === 1 && c.column === 1)).toMatchObject({ text: '960', state: 'VALUE', header_refs: ['R0C1'] });
    expect(regionEdit(figureNode!, figure, null).derived_description).toBe('A tank feeds a filter and a pump.');
    editor.destroy();
  });

  it('allows typing inside a region but never merging, deleting or reordering regions', () => {
    const editor = editorFor(page);
    const before = editor.state.doc.childCount;
    editor.commands.insertContentAt(1, 'X');
    expect(regions(editor)[0]!.textContent).toBe('XCrop allocation');
    editor.commands.deleteRange({ from: 0, to: editor.state.doc.content.size });
    expect(editor.state.doc.childCount).toBe(before);
    const firstEnd = regions(editor)[0]!.nodeSize;
    editor.commands.deleteRange({ from: firstEnd - 2, to: firstEnd + 3 }); // across the region boundary
    expect(regions(editor).map((n) => n.attrs.blockId)).toEqual(['P0001-R0001', 'P0001-R0002', 'P0001-R0003']);
    // Programmatic rebuilds (tagged) are still allowed.
    editor.view.dispatch(editor.state.tr.setMeta(ALLOW_STRUCTURE, true).delete(0, regions(editor)[0]!.nodeSize));
    expect(editor.state.doc.childCount).toBe(before - 1);
    editor.destroy();
  });
});

describe('PageEditor component', () => {
  it('reports region edits made through the inspector', async () => {
    const onChange = vi.fn();
    const ref = createRef<PageEditorHandle>();
    render(<PageEditor ref={ref} page={page} drafts={{}} imageUrl={null} zoom={1} hovered={null}
      onHover={vi.fn()} onActiveRegion={vi.fn()} onChange={onChange} />);
    await waitFor(() => expect(ref.current).toBeTruthy());
    ref.current!.replaceRegionText('P0001-R0001', 'Crop allocation 2026');
    await waitFor(() => expect(onChange).toHaveBeenCalledWith('P0001-R0001', { text: 'Crop allocation 2026' }));
  });
});

describe('Source typography', () => {
  it('keeps the PDF’s mixed bold per word, on a regular-weight region', () => {
    const block: ExtractionBlock = {
      id: 'P0002-R0015', type: 'paragraph', status: 'candidate', native_text: 'Water supplied: 15,680 L.', selected_text: 'Water supplied: 15,680 L.',
      visual: null, consensus: 'native_ocr', bbox_px: [100, 100, 900, 140],
      style: { font_size_px: 40, bold: true, italic: false, color: '#000000', font: 'Lato-Bold', align: 'left' },
    };
    const words = [['Water', true], ['supplied:', true], ['15,680', false], ['L.', false]].map(([text, bold], i) =>
      ({ text: text as string, bold: bold as boolean, bbox_px: [110 + i * 150, 105, 240 + i * 150, 135] }));
    const editor = new Editor({ extensions: editorExtensions, content: pageDocument({ ...page, blocks: [block], native_words: words }, {}, null) });
    expect(editor.getHTML()).toContain('<strong>Water</strong> <strong>supplied:</strong> 15,680 L.');
    expect(regions(editor)[0]!.attrs.fontWeight).toBe('400');
    expect(regionEdit(regions(editor)[0]!, block, null).text).toBe('Water supplied: 15,680 L.');
    editor.destroy();
  });
});

describe('Placing an area extraction', () => {
  it('writes one table cell without touching the others', async () => {
    const onChange = vi.fn();
    const ref = createRef<PageEditorHandle>();
    render(<PageEditor ref={ref} page={page} drafts={{}} imageUrl={null} zoom={1} hovered={null}
      onHover={vi.fn()} onActiveRegion={vi.fn()} onChange={onChange} />);
    await waitFor(() => expect(ref.current).toBeTruthy());
    ref.current!.replaceCell('P0001-R0002', 1, 1, '980');
    await waitFor(() => expect(onChange).toHaveBeenCalledWith('P0001-R0002', expect.objectContaining({ text: 'Zone | Water\nA1 | 980' })));
    const cells = onChange.mock.calls.at(-1)![1].cells;
    expect(cells.find((c: { row: number; column: number }) => c.row === 1 && c.column === 0).text).toBe('A1');
  });
});

describe('Placing part of a region', () => {
  it('replaces only the selected words and keeps the formatting of the rest', async () => {
    const block: ExtractionBlock = {
      id: 'P0001-R0005', type: 'paragraph', status: 'candidate', native_text: 'Site AGR-01: has 600 m2 of area.',
      selected_text: 'Site AGR-01: has\n600 m2 of area.', visual: null, consensus: 'native_ocr', bbox_px: [100, 100, 900, 200],
      style: { font_size_px: 30, bold: false, italic: false, color: '#000000', font: 'Lato', align: 'left' },
    };
    const words = ['Site', 'AGR-01:', 'has', '600', 'm2', 'of', 'area.'].map((text, i) =>
      ({ text, bold: i < 2, bbox_px: [110 + (i % 3) * 120, i < 3 ? 110 : 160, 220 + (i % 3) * 120, i < 3 ? 140 : 190] }));
    const onChange = vi.fn();
    const ref = createRef<PageEditorHandle>();
    render(<PageEditor ref={ref} page={{ ...page, blocks: [block], native_words: words }} drafts={{}} imageUrl={null} zoom={1}
      hovered={null} onHover={vi.fn()} onActiveRegion={vi.fn()} onChange={onChange} />);
    await waitFor(() => expect(ref.current).toBeTruthy());
    ref.current!.replaceWords('P0001-R0005', 3, 4, '600 m²');
    await waitFor(() => expect(onChange).toHaveBeenCalledWith('P0001-R0005', { text: 'Site AGR-01: has\n600 m² of area.' }));
    const html = document.querySelector('[data-block-id="P0001-R0005"]')!.innerHTML;
    expect(html).toContain('<strong>Site</strong> <strong>AGR-01:</strong>');  // untouched words keep their bold
  });
});
