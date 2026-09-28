import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef } from 'react';
import { Mark, Node, type JSONContent, type Editor } from '@tiptap/core';
import type { Node as PMNode } from '@tiptap/pm/model';
import { Plugin, PluginKey } from '@tiptap/pm/state';
import { EditorContent, useEditor } from '@tiptap/react';
import Text from '@tiptap/extension-text';
import HardBreak from '@tiptap/extension-hard-break';
import { UndoRedo } from '@tiptap/extensions';
import { Table, TableCell, TableHeader, TableRow } from '@tiptap/extension-table';
import type { ExtractionBlock, ExtractionPage, ExtractionReading } from '@/lib/api';
import { finalText, regionState, type RegionState } from '@/components/extraction-layout-view';

/** What the editor reports back for one region after an edit. */
export interface RegionEdit { text: string; cells?: ExtractionReading['cells']; derived_description?: string }
export interface PageEditorHandle {
  replaceRegionText: (blockId: string, text: string) => void;
  replaceCell: (blockId: string, row: number, column: number, text: string) => void;
  /** Replace words start..end (inclusive) of a region in place, keeping every other word and its formatting. */
  replaceWords: (blockId: string, start: number, end: number, text: string) => void;
  focusRegion: (blockId: string) => void;
}

type Cell = NonNullable<ExtractionReading['cells']>[number];
export const ALLOW_STRUCTURE = 'extractionAllowStructure';
const NUMERIC = /^[-+−]?[\d.,]+%?$|^[-–]$/;

const percent = (value: number) => `${value.toFixed(4)}%`;
const leaf = (value: string): JSONContent[] => value.split('\n').flatMap((line, index) => [
  ...(index ? [{ type: 'hardBreak' }] : []), ...(line ? [{ type: 'text', text: line }] : []),
]);
const normalize = (value: string) => value.normalize('NFKC').replace(/\s+/g, ' ').trim();
const centerInside = (inner: number[], outer: number[]) => {
  const cx = ((inner[0] ?? 0) + (inner[2] ?? 0)) / 2; const cy = ((inner[1] ?? 0) + (inner[3] ?? 0)) / 2;
  return (outer[0] ?? 0) <= cx && cx <= (outer[2] ?? 0) && (outer[1] ?? 0) <= cy && cy <= (outer[3] ?? 0);
};

/** Region text with the PDF's own bold/italic per word, when the text still matches the source words. */
function styledContent(page: ExtractionPage, block: ExtractionBlock, text: string): { content: JSONContent[]; mixed: boolean } | null {
  const words = (page.native_words ?? []).filter((w) => block.bbox_px && centerInside(w.bbox_px, block.bbox_px));
  if (!words.length || normalize(words.map((w) => w.text).join(' ')) !== normalize(text)) return null;
  const tokens = text.split(/(\s+)/);
  const content: JSONContent[] = []; let index = 0;
  for (const token of tokens) {
    if (!token) continue;
    if (/^\s+$/.test(token)) {
      token.split('\n').forEach((part, i) => {
        if (i) content.push({ type: 'hardBreak' });
        if (part) content.push({ type: 'text', text: part });
      });
      continue;
    }
    const word = words[index++];
    const marks = [...(word?.bold ? [{ type: 'bold' }] : []), ...(word?.italic ? [{ type: 'italic' }] : [])];
    content.push({ type: 'text', text: token, ...(marks.length ? { marks } : {}) });
  }
  const bold = words.filter((w) => w.bold).length;
  return { content, mixed: bold > 0 && bold < words.length };
}

const Bold = Mark.create({ name: 'bold', parseHTML: () => [{ tag: 'strong' }], renderHTML: () => ['strong', 0] });
const Italic = Mark.create({ name: 'italic', parseHTML: () => [{ tag: 'em' }], renderHTML: () => ['em', 0] });

function cssFont(name: string | undefined) {
  const lower = (name ?? '').toLowerCase();
  if (/(courier|mono|consol)/.test(lower)) return 'ui-monospace, "Courier New", monospace';
  if (/(times|serif|georgia|garamond|cambria|tiro)/.test(lower) && !lower.includes('sans')) return '"Times New Roman", Georgia, serif';
  return 'Arial, "Helvetica Neue", Helvetica, sans-serif';
}

let context: CanvasRenderingContext2D | null | undefined;
/** Shrink factor so the widest source line fits its box in the browser's font (1 when unmeasurable). */
function fitFactor(text: string, fontPx: number, family: string, bold: boolean, boxPx: number) {
  if (context === undefined) { try { context = document.createElement('canvas').getContext('2d'); } catch { context = null; } }
  if (!context || !text) return 1;
  context.font = `${bold ? '700 ' : ''}${fontPx}px ${family}`;
  const widest = Math.max(...text.split('\n').map((line) => context!.measureText(line).width));
  return widest > 0 ? Math.min(1, Math.max(0.72, (boxPx * 0.98) / widest)) : 1;
}

/** Position and typography of a region, in page-relative units so the page scales with zoom. */
function placement(page: ExtractionPage, block: ExtractionBlock, text: string) {
  const width = page.width_px ?? 1000; const height = page.height_px ?? 1414;
  const [x0, y0, x1, y1] = (block.bbox_px ?? [0, 0, 0, 0]) as [number, number, number, number];
  const style = block.style;
  const lines = Math.max(1, text.split('\n').length);
  const fallback = Math.min(((y1 - y0) / lines) * 0.72, 40);
  const family = cssFont(style?.font);
  const base = style?.font_size_px ?? fallback;
  const size = base * fitFactor(text, base, family, Boolean(style?.bold), x1 - x0);
  return {
    left: percent((x0 / width) * 100), top: percent((y0 / height) * 100),
    width: percent(((x1 - x0) / width) * 100), minHeight: percent(((y1 - y0) / height) * 100),
    fontSize: `${((size / width) * 100).toFixed(4)}cqw`, fontFamily: family,
    fontWeight: style?.bold ? '700' : '400', fontStyle: style?.italic ? 'italic' : 'normal',
    color: style?.color && style.color !== '#000000' ? style.color : '', textAlign: style?.align ?? 'left',
  };
}

const style = (attrs: Record<string, string>) => Object.entries({
  left: attrs.left, top: attrs.top, width: attrs.width, 'min-height': attrs.minHeight, 'font-size': attrs.fontSize,
  'font-family': attrs.fontFamily, 'font-weight': attrs.fontWeight, 'font-style': attrs.fontStyle,
  color: attrs.color, 'text-align': attrs.textAlign,
}).filter(([, v]) => v).map(([k, v]) => `${k}:${v}`).join(';');

const regionAttributes = {
  blockId: { default: '' }, kind: { default: 'paragraph' }, state: { default: 'match' },
  left: { default: '0%' }, top: { default: '0%' }, width: { default: '0%' }, minHeight: { default: '0%' },
  fontSize: { default: '1cqw' }, fontFamily: { default: '' }, fontWeight: { default: '400' },
  fontStyle: { default: 'normal' }, color: { default: '' }, textAlign: { default: 'left' },
};

const regionTag = (attrs: Record<string, string>, extra: string) => ({
  'data-block-id': attrs.blockId, 'data-kind': attrs.kind,
  class: `xe-region xe-state--${attrs.state} ${extra}`, style: style(attrs),
});

const PageDocument = Node.create({ name: 'doc', topNode: true, content: 'region+' });

const SourceText = Node.create({
  name: 'sourceText', group: 'region', content: 'inline*', isolating: true, defining: true,
  addAttributes: () => regionAttributes,
  parseHTML: () => [{ tag: 'div[data-kind]:not([data-table]):not([data-figure])' }],
  renderHTML: ({ node }) => ['div', regionTag(node.attrs as Record<string, string>, node.attrs.kind === 'heading' ? 'xe-heading' : ''), 0],
  addKeyboardShortcuts() {
    return { Enter: () => this.editor.commands.setHardBreak(), 'Shift-Enter': () => this.editor.commands.setHardBreak() };
  },
});

const SourceTable = Node.create({
  name: 'sourceTable', group: 'region', content: 'table', isolating: true,
  addAttributes: () => regionAttributes,
  parseHTML: () => [{ tag: 'div[data-table]' }],
  renderHTML: ({ node }) => ['div', { ...regionTag(node.attrs as Record<string, string>, 'xe-table'), 'data-table': '' }, 0],
});

const SourceFigure = Node.create({
  name: 'sourceFigure', group: 'region', content: 'inline*', isolating: true,
  addAttributes: () => ({ ...regionAttributes, image: { default: '' }, imageSize: { default: '' }, imagePosition: { default: '' } }),
  parseHTML: () => [{ tag: 'div[data-figure]' }],
  renderHTML: ({ node }) => {
    const attrs = node.attrs as Record<string, string>;
    return ['div', { ...regionTag(attrs, 'xe-figure'), 'data-figure': '' },
      ['div', { class: 'xe-figure__image', contenteditable: 'false', 'aria-hidden': 'true',
        style: attrs.image ? `background-image:url("${attrs.image}");background-size:${attrs.imageSize};background-position:${attrs.imagePosition}` : '' }],
      ['div', { class: 'xe-figure__label', contenteditable: 'false' }, 'AI description · not source text'],
      ['p', { class: 'xe-figure__text' }, 0]];
  },
});

const cellAttributes = { cellKey: { default: '' }, align: { default: 'left' }, widthPct: { default: '' }, disputed: { default: false } };
const cellHTML = (attrs: Record<string, unknown>) => ({
  'data-cell': attrs.cellKey, class: attrs.disputed ? 'xe-cell is-disputed' : 'xe-cell',
  style: [attrs.widthPct ? `width:${attrs.widthPct}` : '', `text-align:${attrs.align}`].filter(Boolean).join(';'),
  ...(attrs.colspan && Number(attrs.colspan) > 1 ? { colspan: attrs.colspan } : {}),
});
const EditorCell = TableCell.extend({
  content: 'inline*',
  addAttributes() { return { ...this.parent?.(), ...cellAttributes }; },
  renderHTML({ node }) { return ['td', cellHTML(node.attrs), 0]; },
});
const EditorHeader = TableHeader.extend({
  content: 'inline*',
  addAttributes() { return { ...this.parent?.(), ...cellAttributes }; },
  renderHTML({ node }) { return ['th', cellHTML(node.attrs), 0]; },
});

/** Signature of everything a reviewer must not change: which regions exist, their order, table shapes. */
function structureOf(doc: PMNode) {
  const parts: string[] = [];
  doc.forEach((region) => {
    let shape = '';
    if (region.type.name === 'sourceTable') region.firstChild?.forEach((row) => { shape += `${row.childCount},`; });
    parts.push(`${region.type.name}:${String(region.attrs.blockId)}:${shape}`);
  });
  return parts.join('|');
}

const ProtectStructure = Node.create({
  name: 'protectStructure', group: 'none',
  addProseMirrorPlugins() {
    return [new Plugin({
      key: new PluginKey('protectStructure'),
      filterTransaction: (tr, state) => !tr.docChanged || Boolean(tr.getMeta(ALLOW_STRUCTURE)) || structureOf(tr.doc) === structureOf(state.doc),
    })];
  },
});

/** Everything the page editor is built from; exported so tests can use the real schema. */
export const editorExtensions = [PageDocument, Text, HardBreak, UndoRedo, Bold, Italic, SourceText, SourceTable, SourceFigure,
  Table.configure({ resizable: false }), TableRow, EditorHeader, EditorCell, ProtectStructure];

/** The PDF page as one editor document: regions in reading order, each placed and styled like the source. */
export function pageDocument(page: ExtractionPage, drafts: Record<string, ExtractionReading | null>, imageUrl: string | null): JSONContent {
  const width = page.width_px ?? 1000; const height = page.height_px ?? 1414;
  const regions = (page.blocks ?? []).filter((b) => b.status !== 'split' && b.bbox_px);
  const content: JSONContent[] = regions.map((block) => {
    const draft = drafts[block.id] ?? null;
    const text = finalText(block, draft);
    const state: RegionState = regionState(block, text);
    const attrs = { blockId: block.id, kind: block.type, state, ...placement(page, block, text) };
    const cells: Cell[] = draft?.cells?.length ? draft.cells : (block.proposed_structure?.cells ?? []);
    if (cells.length) {
      const [bx0, , bx1] = block.bbox_px as [number, number, number, number];
      const bounds = block.native_table?.column_bounds;
      const disputed = new Set((block.cell_checks ?? []).filter((c) => !c.confirmed).map((c) => `${c.row},${c.column}`));
      const numericColumn = (column: number) => {
        const values = cells.filter((c) => c.column === column && !c.header && c.text);
        return values.length > 0 && values.filter((c) => NUMERIC.test(c.text.trim())).length >= values.length * 0.6;
      };
      const rows = [...new Set(cells.map((c) => c.row))].sort((a, b) => a - b);
      return {
        type: 'sourceTable', attrs,
        content: [{ type: 'table', content: rows.map((row) => ({
          type: 'tableRow',
          content: cells.filter((c) => c.row === row).sort((a, b) => a.column - b.column).map((cell) => {
            const span = cell.column_span ?? 1;
            const column = bounds?.slice(cell.column, cell.column + span);
            const first = column?.[0]; const last = column?.[column.length - 1];
            const widthPct = row === rows[0] && first && last
              ? percent((((last[1] ?? 0) - (first[0] ?? 0) + 12) / Math.max(1, bx1 - bx0)) * 100) : '';
            return {
              type: cell.header ? 'tableHeader' : 'tableCell',
              attrs: { colspan: span, cellKey: `${cell.row},${cell.column}`, align: numericColumn(cell.column) ? 'right' : 'left',
                widthPct, disputed: disputed.has(`${cell.row},${cell.column}`) },
              content: leaf(cell.text),
            };
          }),
        })) }],
      };
    }
    const isFigure = Boolean(block.figure_description) || (block.type === 'figure' && !block.native_text);
    if (isFigure) {
      const [x0, y0, x1, y1] = block.bbox_px as [number, number, number, number];
      const boxW = Math.max(1, x1 - x0); const boxH = Math.max(1, y1 - y0);
      return {
        type: 'sourceFigure',
        attrs: { ...attrs, image: imageUrl ?? '', imageSize: `${(width / boxW) * 100}% ${(height / boxH) * 100}%`,
          imagePosition: `${(x0 / Math.max(1, width - boxW)) * 100}% ${(y0 / Math.max(1, height - boxH)) * 100}%` },
        content: leaf(String(draft?.derived_description ?? block.figure_description ?? '')),
      };
    }
    const styled = styledContent(page, block, text);
    // Mixed weights are drawn per word, so the region itself uses the regular weight.
    return { type: 'sourceText', attrs: styled?.mixed ? { ...attrs, fontWeight: '400' } : attrs, content: styled?.content ?? leaf(text) };
  });
  return { type: 'doc', content: content.length ? content : [{ type: 'sourceText', attrs: { blockId: '', state: 'single' }, content: leaf(page.selected_text ?? page.native_text) }] };
}

const textOf = (node: PMNode) => node.textBetween(0, node.content.size, '\n', (n) => (n.type.name === 'hardBreak' ? '\n' : ''));

/** Read one region back out of the editor. */
export function regionEdit(node: PMNode, original: ExtractionBlock | undefined, draft: ExtractionReading | null): RegionEdit {
  if (node.type.name === 'sourceTable') {
    const source: Cell[] = draft?.cells?.length ? draft.cells : (original?.proposed_structure?.cells ?? []);
    const byKey = new Map(source.map((c) => [`${c.row},${c.column}`, c]));
    const cells: Cell[] = []; const lines: string[] = [];
    node.firstChild?.forEach((row) => {
      const values: string[] = [];
      row.forEach((cell) => {
        const text = textOf(cell);
        const base = byKey.get(String(cell.attrs.cellKey));
        if (base) cells.push({ ...base, text, state: text ? 'VALUE' : 'BLANK' });
        values.push(text);
      });
      lines.push(values.join(' | '));
    });
    return { text: lines.join('\n'), cells };
  }
  if (node.type.name === 'sourceFigure') return { text: finalText(original ?? ({} as ExtractionBlock), draft), derived_description: textOf(node) };
  return { text: textOf(node) };
}

export const PageEditor = forwardRef<PageEditorHandle, {
  page: ExtractionPage;
  drafts: Record<string, ExtractionReading | null>;
  imageUrl: string | null;
  zoom: number;
  readOnly?: boolean;
  hovered: string | null;
  onHover: (id: string | null) => void;
  onActiveRegion: (id: string | null) => void;
  onChange: (blockId: string, edit: RegionEdit) => void;
}>(function PageEditor({ page, drafts, imageUrl, zoom, readOnly = false, hovered, onHover, onActiveRegion, onChange }, ref) {
  const blocks = useMemo(() => new Map((page.blocks ?? []).map((b) => [b.id, b])), [page.blocks]);
  const latest = useRef({ drafts, blocks, onChange, onActiveRegion, onHover });
  latest.current = { drafts, blocks, onChange, onActiveRegion, onHover };
  const width = page.width_px ?? 1000; const height = page.height_px ?? 1414;

  const editor = useEditor({
    extensions: editorExtensions,
    content: pageDocument(page, drafts, imageUrl),
    editable: !readOnly,
    editorProps: {
      attributes: { class: 'xe-page', 'aria-label': `Extracted text of page ${page.number}, editable`, role: 'textbox', 'aria-multiline': 'true' },
      handlePaste: (view, event) => {
        // Paste plain text only, so formatting and structure always come from the source.
        const text = event.clipboardData?.getData('text/plain');
        if (text === undefined) return false;
        view.dispatch(view.state.tr.insertText(text.replace(/\r\n?/g, '\n').replace(/\n/g, ' ')));
        return true;
      },
      handleDOMEvents: {
        mouseover: (_view, event) => {
          const id = (event.target as HTMLElement | null)?.closest?.('[data-block-id]')?.getAttribute('data-block-id');
          latest.current.onHover(id || null);
          return false;
        },
        mouseleave: () => { latest.current.onHover(null); return false; },
      },
    },
    onUpdate: ({ editor: instance, transaction }) => {
      if (!transaction.docChanged || transaction.getMeta(ALLOW_STRUCTURE)) return;
      instance.state.doc.forEach((node) => {
        const id = String(node.attrs.blockId);
        if (!id) return;
        const edit = regionEdit(node, latest.current.blocks.get(id), latest.current.drafts[id] ?? null);
        const draft = latest.current.drafts[id] ?? null;
        const previous = node.type.name === 'sourceFigure' ? String(draft?.derived_description ?? latest.current.blocks.get(id)?.figure_description ?? '')
          : node.type.name === 'sourceTable' ? null : finalText(latest.current.blocks.get(id)!, draft);
        if (node.type.name === 'sourceTable' ? JSON.stringify(edit.cells?.map((c) => c.text)) !== JSON.stringify((draft?.cells ?? latest.current.blocks.get(id)?.proposed_structure?.cells ?? []).map((c) => c.text))
          : (node.type.name === 'sourceFigure' ? edit.derived_description : edit.text) !== previous) {
          latest.current.onChange(id, edit);
        }
      });
    },
    onSelectionUpdate: ({ editor: instance }) => latest.current.onActiveRegion(activeRegion(instance)),
  }, [page.number]);

  // Keep region colouring in step with drafts without rebuilding (and losing the caret).
  useEffect(() => {
    if (!editor) return;
    const { tr } = editor.state;
    let changed = false;
    editor.state.doc.forEach((node, offset) => {
      const block = blocks.get(String(node.attrs.blockId));
      if (!block) return;
      const state = regionState(block, finalText(block, drafts[block.id] ?? null));
      if (node.attrs.state !== state) { tr.setNodeMarkup(offset, undefined, { ...node.attrs, state }); changed = true; }
    });
    if (changed) editor.view.dispatch(tr.setMeta(ALLOW_STRUCTURE, true).setMeta('addToHistory', false));
  }, [editor, drafts, blocks]);

  useEffect(() => { editor?.setEditable(!readOnly); }, [editor, readOnly]);

  useImperativeHandle(ref, () => ({
    replaceRegionText: (blockId, text) => {
      if (!editor) return;
      editor.state.doc.forEach((node, offset) => {
        if (String(node.attrs.blockId) !== blockId || node.type.name !== 'sourceText') return;
        const content = leaf(text).map((part) => editor.schema.nodeFromJSON(part));
        editor.view.dispatch(editor.state.tr.replaceWith(offset + 1, offset + node.nodeSize - 1, content));
      });
    },
    replaceWords: (blockId, start, end, text) => {
      if (!editor) return;
      editor.state.doc.forEach((node, offset) => {
        if (String(node.attrs.blockId) !== blockId || node.type.name !== 'sourceText') return;
        // Flatten the region to characters with their document positions, then find the words.
        const chars: Array<{ char: string; pos: number }> = [];
        node.forEach((child, childOffset) => {
          const base = offset + 1 + childOffset;
          // UTF-16 units, matching how ProseMirror counts positions.
          if (child.isText) (child.text ?? '').split('').forEach((char, i) => chars.push({ char, pos: base + i }));
          else chars.push({ char: '\n', pos: base });
        });
        const flat = chars.map((c) => c.char).join('');
        const words = [...flat.matchAll(/\S+/g)].map((m) => ({ from: m.index, to: m.index + m[0].length }));
        const first = words[start]; const last = words[end];
        if (!first || !last) return;
        const from = chars[first.from]!.pos; const to = chars[last.to - 1]!.pos + 1;
        editor.view.dispatch(editor.state.tr.insertText(text, from, to));
      });
    },
    replaceCell: (blockId, row, column, text) => {
      if (!editor) return;
      editor.state.doc.forEach((node, offset) => {
        if (String(node.attrs.blockId) !== blockId || node.type.name !== 'sourceTable') return;
        node.descendants((child, pos) => {
          if (child.attrs.cellKey !== `${row},${column}`) return true;
          const from = offset + 1 + pos + 1;
          const content = leaf(text).map((part) => editor.schema.nodeFromJSON(part));
          editor.view.dispatch(editor.state.tr.replaceWith(from, from + child.content.size, content));
          return false;
        });
      });
    },
    focusRegion: (blockId) => {
      if (!editor) return;
      editor.state.doc.forEach((node, offset) => {
        if (String(node.attrs.blockId) === blockId) {
          editor.chain().focus().setTextSelection(offset + 1).run();
          editor.view.dom.querySelector(`[data-block-id="${blockId}"]`)?.scrollIntoView({ block: 'center', behavior: 'smooth' });
        }
      });
    },
  }), [editor]);

  return <div className={`xe-canvas${hovered ? ' has-hover' : ''}`} style={{ width: `${zoom * 100}%`, aspectRatio: `${width} / ${height}` }}
    data-hovered={hovered ?? undefined}>
    <style>{hovered ? `.xe-canvas [data-block-id="${hovered}"]{outline:2px solid #0c0b0b;outline-offset:2px;background:#fff3a855}` : ''}</style>
    <EditorContent editor={editor} className="xe-editor" />
  </div>;
});

function activeRegion(editor: Editor): string | null {
  const { $from } = editor.state.selection;
  for (let depth = $from.depth; depth > 0; depth -= 1) {
    const id = $from.node(depth).attrs.blockId;
    if (id) return String(id);
  }
  return null;
}
