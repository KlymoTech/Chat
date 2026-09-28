import type { ExtractionBlock, ExtractionPage, ExtractionReading, ExtractionWord } from '@/lib/api';

/** How a region's final text was established, used for colour-coding both page views. */
export type RegionState = 'match' | 'consensus' | 'single' | 'edited' | 'conflict' | 'failed';

export const REGION_STATE_LABELS: Record<RegionState, string> = {
  match: 'Readers agree',
  consensus: 'Resolved 2 of 3',
  single: 'One reader only',
  edited: 'Edited in review',
  conflict: 'Needs your decision',
  failed: 'Not read',
};

const normalize = (value: string) => value.normalize('NFKC')
  .replace(/[‘’]/g, "'").replace(/[“”]/g, '"').replace(/[–—−]/g, '-')
  .replace(/\s+/g, ' ').trim();

const centerInside = (inner: number[], outer: number[]) => {
  const cx = (inner[0]! + inner[2]!) / 2; const cy = (inner[1]! + inner[3]!) / 2;
  return outer[0]! <= cx && cx <= outer[2]! && outer[1]! <= cy && cy <= outer[3]!;
};

export function finalText(block: ExtractionBlock, draft: ExtractionReading | null): string {
  return draft?.text ?? block.selected_text ?? block.proposed_structure?.text ?? block.visual?.text ?? '';
}

export function regionState(block: ExtractionBlock, text: string): RegionState {
  if (!block.visual && !block.proposed_structure) return 'failed';
  const baseline = block.selected_text;
  if (baseline === null || baseline === undefined) {
    if (!block.native_text && !block.ocr_text) return 'single';
    // Unchanged from the pipeline's draft means nobody has decided yet.
    const initial = block.proposed_structure?.text ?? block.visual?.text ?? '';
    return normalize(text) === normalize(initial) ? 'conflict' : 'edited';
  }
  if (normalize(text) !== normalize(baseline)) return 'edited';
  return block.consensus === 'native_ocr' ? 'consensus' : 'match';
}

/** Source words to draw at their exact positions, when they spell the region's final text. */
function positionedWords(page: ExtractionPage, block: ExtractionBlock, text: string): ExtractionWord[] | null {
  const box = block.bbox_px;
  if (!box) return null;
  for (const words of [page.native_words, page.ocr_words]) {
    const inside = (words ?? []).filter((w) => centerInside(w.bbox_px, box));
    if (inside.length && normalize(inside.map((w) => w.text).join(' ')) === normalize(text)) return inside;
  }
  return null;
}

const FONT_FAMILY = 'Arial, "Helvetica Neue", sans-serif';
let measureContext: CanvasRenderingContext2D | null | undefined;

/** Horizontal stretch that makes a word span exactly its source width (1 when unmeasurable). */
function widthScale(text: string, fontPx: number, targetPx: number) {
  if (measureContext === undefined) {
    try { measureContext = document.createElement('canvas').getContext('2d'); } catch { measureContext = null; }
  }
  if (!measureContext || fontPx <= 0) return 1;
  measureContext.font = `${fontPx}px ${FONT_FAMILY}`;
  const natural = measureContext.measureText(text).width;
  return natural > 0 ? Math.min(2.5, Math.max(0.4, targetPx / natural)) : 1;
}

function medianWordHeight(page: ExtractionPage) {
  const heights = (page.native_words ?? []).map((w) => w.bbox_px[3]! - w.bbox_px[1]!).sort((a, b) => a - b);
  return heights.length ? heights[Math.floor(heights.length / 2)]! : null;
}

export function ExtractedPageView({ page, drafts, zoom, hovered, onHover, onSelect }: {
  page: ExtractionPage;
  drafts: Record<string, ExtractionReading | null>;
  zoom: number;
  hovered: string | null;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
}) {
  const width = page.width_px ?? 1000;
  const height = page.height_px ?? 1414;
  const leaves = (page.blocks ?? []).filter((b) => b.status !== 'split' && b.bbox_px);
  const typical = medianWordHeight(page);
  // Font sizes are in container-width units, so the page scales with zoom like the image does.
  const cqw = (px: number) => `${(px / width) * 100}cqw`;
  return <div className="xl-page" style={{ width: `${zoom * 100}%`, aspectRatio: `${width} / ${height}` }}
    role="img" aria-label={`Extracted text laid out like source page ${page.number}`}>
    {!leaves.length && page.selected_text && <pre className="xl-plain" style={{ fontSize: cqw(typical ? typical * 0.8 : 28) }}>{page.selected_text}</pre>}
    {leaves.map((block) => {
      const box = block.bbox_px!;
      const text = finalText(block, drafts[block.id] ?? null);
      const state = regionState(block, text);
      const [x0, y0, x1, y1] = box as [number, number, number, number];
      const boxWidth = Math.max(1, x1 - x0); const boxHeight = Math.max(1, y1 - y0);
      // Only true images are figures; drawings holding PDF text (tables, callouts) render as text.
      const isFigure = Boolean(block.figure_description) || (block.type === 'figure' && !block.native_text);
      const words = isFigure ? null : positionedWords(page, block, text);
      const lines = text.split('\n');
      const longest = Math.max(1, ...lines.map((l) => l.length));
      const fitted = Math.min(boxHeight / (lines.length * 1.3), boxWidth / (longest * 0.55), typical ? typical * 0.9 : Infinity);
      return <div key={block.id} className={`xl-region xl-region--${state}${hovered === block.id ? ' is-hover' : ''}${isFigure ? ' xl-region--figure' : ''}`}
        style={{ left: `${(x0 / width) * 100}%`, top: `${(y0 / height) * 100}%`, width: `${(boxWidth / width) * 100}%`, height: `${(boxHeight / height) * 100}%` }}
        title={`${block.id} · ${REGION_STATE_LABELS[state]}`}
        onMouseEnter={() => onHover(block.id)} onMouseLeave={() => onHover(null)} onClick={() => onSelect(block.id)}>
        {isFigure ? <div className="xl-figure" style={{ fontSize: cqw(Math.max(14, (typical ?? 30) * 0.7)) }}>
          <span className="xl-figure__tag">Figure · AI description, not source text</span>
          {text && <strong>{text}</strong>}
          <p>{block.figure_description ?? 'No description generated. Describe this figure during review.'}</p>
        </div>
          : words ? words.map((w, index) => {
            const [wx0, wy0, wx1, wy1] = w.bbox_px as [number, number, number, number];
            const fontPx = (wy1 - wy0) * (page.native_words?.includes(w) ? 0.82 : 1.1);
            return <span key={index} className="xl-word" style={{
              left: `${((wx0 - x0) / boxWidth) * 100}%`, top: `${((wy0 - y0) / boxHeight) * 100}%`,
              fontSize: cqw(fontPx), transform: `scaleX(${widthScale(w.text, fontPx, wx1 - wx0)})`,
            }}>{w.text}</span>;
          })
            : <span className="xl-flow" style={{ fontSize: cqw(Math.max(8, fitted)) }}>{text || ' '}</span>}
      </div>;
    })}
  </div>;
}

/** Region outlines drawn over the original page image, in the same coordinates. */
export function SourceRegionOverlay({ page, drafts, hovered, onHover, onSelect }: {
  page: ExtractionPage;
  drafts: Record<string, ExtractionReading | null>;
  hovered: string | null;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
}) {
  const width = page.width_px ?? 1; const height = page.height_px ?? 1;
  return <div className="xl-overlay" aria-hidden="true">
    {(page.blocks ?? []).filter((b) => b.status !== 'split' && b.bbox_px).map((block) => {
      const [x0, y0, x1, y1] = block.bbox_px as [number, number, number, number];
      const state = regionState(block, finalText(block, drafts[block.id] ?? null));
      return <div key={block.id} className={`xl-region xl-region--${state} xl-region--outline${hovered === block.id ? ' is-hover' : ''}`}
        style={{ left: `${(x0 / width) * 100}%`, top: `${(y0 / height) * 100}%`, width: `${((x1 - x0) / width) * 100}%`, height: `${((y1 - y0) / height) * 100}%` }}
        onMouseEnter={() => onHover(block.id)} onMouseLeave={() => onHover(null)} onClick={() => onSelect(block.id)} />;
    })}
  </div>;
}
