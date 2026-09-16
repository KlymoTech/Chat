import { describe, expect, it } from 'vitest';
import { buildPageReview, newPageDraft } from './extraction-review-state';
import type { SourcePage } from './extraction-api';

const page: SourcePage = {
  number: 1, source_unit: 'pdf_page', native_text: 'Do NOT omit −12.50.', visual_text: 'Do NOT omit −12.50.',
  selected_text: 'Do NOT omit −12.50.', image: 'pages/page_0001.png', requires_image: true,
  blocks: [{ id: 'P1-R1', type: 'question', status: 'candidate', selected_text: 'Do NOT omit −12.50.',
    visual: { kind: 'question', text: 'Do NOT omit −12.50.', complete: true, options: [], option_labels: [] } }],
};

describe('source review payload', () => {
  it('never carries forward source confirmation or a generic review reason', () => {
    const draft = newPageDraft(page);
    expect(draft.confirmed).toBe(false);
    expect(draft.reason).toBe('');
    expect(() => buildPageReview(page, draft)).toThrow('confirm');
  });
  it('submits exact block-derived text and the current structured contract', () => {
    const draft = { ...newPageDraft(page), confirmed: true, reason: 'Compared the retained source image.' };
    const result = buildPageReview(page, draft);
    expect(result.selectedText).toBe('Do NOT omit −12.50.');
    expect(result.structureConfirmed).toBe(true);
    expect(result.blocks[0]?.structure.kind).toBe('question');
  });
  it('rejects malformed, incomplete, and uncertain structures', () => {
    for (const value of ['{', 'null', '{"kind":"question","text":"Source","complete":false}', '{"kind":"question","text":"Source","complete":true,"uncertain":true}']) {
      const draft = { ...newPageDraft(page), confirmed: true, reason: 'Source compared.', structures: { 'P1-R1': value } };
      expect(() => buildPageReview(page, draft)).toThrow();
    }
  });
  it('rejects duplicate source links instead of silently normalizing them', () => {
    const draft = { ...newPageDraft(page), confirmed: true, reason: 'Source compared.', relationships: { 'P1-R1': 'P2-R1, P2-R1' } };
    expect(() => buildPageReview(page, draft)).toThrow('duplicate');
  });
  it('requires explicit blank confirmation', () => {
    const blank = { ...page, blocks: [], native_text: '', selected_text: '', visual_text: '' };
    const draft = { ...newPageDraft(blank), confirmed: true, reason: 'Checked original.' };
    expect(() => buildPageReview(blank, draft)).toThrow('blank');
    expect(buildPageReview(blank, { ...draft, blankConfirmed: true }).selectedText).toBe('');
  });
  it('does not permit a text-file source rewrite', () => {
    const text = { ...page, blocks: [], source_unit: 'bytes' };
    const draft = { ...newPageDraft(text), confirmed: true, reason: 'Checked bytes.', text: 'Changed source.' };
    expect(() => buildPageReview(text, draft)).toThrow('authoritative');
  });
});
