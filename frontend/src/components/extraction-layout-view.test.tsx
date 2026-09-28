import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ExtractedPageView, regionState } from '@/components/extraction-layout-view';
import type { ExtractionBlock, ExtractionPage } from '@/lib/api';

afterEach(cleanup);

const block = (overrides: Partial<ExtractionBlock>): ExtractionBlock => ({
  id: 'P0001-R0001', type: 'paragraph', status: 'candidate', native_text: 'Value -12.50', selected_text: 'Value -12.50',
  visual: { kind: 'paragraph', text: 'Value -12.50', complete: true }, bbox_px: [100, 100, 500, 140], consensus: 'native_vision', ...overrides,
});

const page = (blocks: ExtractionBlock[]): ExtractionPage => ({
  number: 1, native_text: 'Value -12.50', visual_text: null, selected_text: null, image: 'p.png', width_px: 1000, height_px: 1400, blocks,
  native_words: [{ text: 'Value', bbox_px: [110, 105, 200, 135] }, { text: '-12.50', bbox_px: [210, 105, 330, 135] }],
});

describe('Extracted page layout', () => {
  it('places each source word at its position on the page', () => {
    render(<ExtractedPageView page={page([block({})])} drafts={{}} zoom={1} hovered={null} onHover={vi.fn()} onSelect={vi.fn()} />);
    const word = screen.getByText('-12.50');
    expect(word).toHaveClass('xl-word');
    expect(parseFloat(word.style.left)).toBeCloseTo(27.5); // (210 - 100) / 400
  });

  it('falls back to fitted text when a reviewer edits the region', () => {
    render(<ExtractedPageView page={page([block({})])} drafts={{ 'P0001-R0001': { kind: 'paragraph', text: 'Value -12.80', complete: true } }}
      zoom={1} hovered={null} onHover={vi.fn()} onSelect={vi.fn()} />);
    expect(screen.getByText('Value -12.80')).toHaveClass('xl-flow');
    expect(screen.getByTitle(/Edited in review/)).toBeInTheDocument();
  });

  it('shows figure descriptions as AI descriptions, separate from source text', () => {
    render(<ExtractedPageView page={page([block({ type: 'figure', native_text: '', selected_text: null, visual: { kind: 'figure', text: 'Tank T-01', complete: true },
      figure_description: 'A tank feeds a filter and a pump.' })])} drafts={{}} zoom={1} hovered={null} onHover={vi.fn()} onSelect={vi.fn()} />);
    expect(screen.getByText(/AI description, not source text/)).toBeInTheDocument();
    expect(screen.getByText('A tank feeds a filter and a pump.')).toBeInTheDocument();
  });

  it('classifies how each region was settled', () => {
    expect(regionState(block({}), 'Value -12.50')).toBe('match');
    expect(regionState(block({ consensus: 'native_ocr' }), 'Value -12.50')).toBe('consensus');
    expect(regionState(block({ selected_text: null, consensus: undefined, visual: { kind: 'paragraph', text: 'Value 12.50', complete: true } }), 'Value 12.50')).toBe('conflict');
    expect(regionState(block({ visual: null, proposed_structure: undefined }), '')).toBe('failed');
  });
});
