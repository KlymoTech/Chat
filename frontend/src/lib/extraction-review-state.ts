import type { ReviewPageInput, SourcePage, SourceReading } from '@/lib/extraction-api';

export interface PageDraft {
  reason: string;
  confirmed: boolean;
  blankConfirmed: boolean;
  text: string;
  structures: Record<string, string>;
  relationships: Record<string, string>;
}

export function newPageDraft(page: SourcePage): PageDraft {
  return {
    reason: '', confirmed: false, blankConfirmed: false,
    text: page.selected_text ?? page.native_text ?? '',
    structures: Object.fromEntries(page.blocks.filter((block) => block.status !== 'split').map((block) => [
      block.id, JSON.stringify(block.reviewed_structure ?? block.visual ?? null, null, 2),
    ])),
    relationships: Object.fromEntries(page.blocks.map((block) => [block.id, (block.related_block_ids ?? []).join(', ')])),
  };
}

export function buildPageReview(page: SourcePage, draft: PageDraft): ReviewPageInput {
  if (!draft.confirmed || !draft.reason.trim()) throw new Error(`Unit ${page.number}: confirm the source and provide a review reason.`);
  const blocks = page.blocks.filter((block) => block.status !== 'split').map((block) => {
    const value: unknown = JSON.parse(draft.structures[block.id] ?? 'null');
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${block.id}: enter a structured source reading.`);
    const reading = value as SourceReading;
    if (typeof reading.kind !== 'string' || typeof reading.text !== 'string' || reading.complete !== true || reading.uncertain === true) {
      throw new Error(`${block.id}: incomplete or uncertain content cannot be approved.`);
    }
    const relatedBlockIds = (draft.relationships[block.id] ?? '').split(',').map((id) => id.trim()).filter(Boolean);
    if (new Set(relatedBlockIds).size !== relatedBlockIds.length) throw new Error(`${block.id}: duplicate source relationship.`);
    return { id: block.id, selectedText: reading.text, structure: reading, relatedBlockIds };
  });
  const selectedText = blocks.length ? blocks.map((block) => block.selectedText).join('\n') : draft.text;
  if (page.source_unit === 'bytes' && selectedText !== page.native_text) throw new Error('Text-file bytes are authoritative. Do not rewrite the source.');
  if (selectedText.includes('[[UNREADABLE]]')) throw new Error('Unreadable content must remain blocked.');
  if (!selectedText && !blocks.length && !draft.blankConfirmed) throw new Error('Explicitly confirm a blank source.');
  return { number: page.number, selectedText, reason: draft.reason, structureConfirmed: true,
    blankConfirmed: draft.blankConfirmed, blocks };
}
