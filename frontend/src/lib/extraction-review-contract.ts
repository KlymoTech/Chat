/** Wire types for the existing versioned, workspace-scoped extraction endpoints. */
export interface SourceStructure {
  kind: string;
  text: string;
  complete: boolean;
  uncertain?: boolean;
  cells?: Array<{ row: number; column: number; text: string; state: string; row_span?: number; column_span?: number; header_refs?: string[] }>;
  [key: string]: unknown;
}
export interface EvidenceBlock {
  id: string; type: string; status: string; native_text?: string;
  selected_text: string | null; visual: SourceStructure | null;
  reviewed_structure?: SourceStructure; review_candidate?: SourceStructure; related_block_ids?: string[];
  bbox_px: number[]; crop?: string;
}
export interface EvidencePage {
  number: number; native_text: string; visual_text: string | null;
  selected_text: string | null; image: string | null; source_unit?: string;
  requires_image?: boolean; requires_second_review?: boolean;
  source_page_number?: number | null; rendered_page_number?: number | null;
  printed_page_label?: string | null; pdf_page_label?: string | null;
  primary_review?: { reviewer: string }; second_review?: { reviewer: string };
  blocks: EvidenceBlock[];
}
export interface EvidenceIssue {
  id: string; page: number; code: string; message: string; technical?: boolean;
  status?: string; disposition?: 'source_verified' | 'source_anomaly' | 'unresolved'; resolution_reason?: string;
}
export interface EvidenceRecord {
  schema_version: number; extraction_revision: number; source_sha256: string;
  review_status: string; pages: EvidencePage[]; issues: EvidenceIssue[];
  word?: { blocks: Array<{id: string; part: string; text: string; mapping_status: string; rendered_pages: number[]}> };
  release_blockers?: string[]; checks?: Array<{ name: string; status: string; details: string[] }>;
}
export interface BlockDraft { id: string; text: string; structureJson: string; relatedIds: string }
export interface PageDraft { number: number; text: string; reason: string; confirmed: boolean; blankConfirmed: boolean; blocks: BlockDraft[] }
export interface IssueDraft { id: string; action: 'source_verified' | 'source_anomaly' | 'unresolved'; reason: string }

export function createDrafts(record: EvidenceRecord): PageDraft[] {
  return record.pages.map((page) => ({
    number: page.number, text: page.selected_text ?? page.native_text ?? '', reason: '', confirmed: false,
    blankConfirmed: false,
    blocks: (page.blocks ?? []).filter((block) => block.status !== 'split').map((block) => {
      const structure = block.reviewed_structure ?? block.visual;
      return { id: block.id, text: structure?.text ?? '', structureJson: JSON.stringify(structure, null, 2),
        relatedIds: (block.related_block_ids ?? []).join(', ') };
    }),
  }));
}

export function buildApproval(record: EvidenceRecord, drafts: PageDraft[], decisions: IssueDraft[]) {
  if (!Number.isInteger(record.extraction_revision) || record.extraction_revision < 1) {
    throw new Error('Evidence has no current revision. Retry extraction before reviewing.');
  }
  if (drafts.length !== record.pages.length || drafts.some((page, i) => page.number !== record.pages[i]?.number || !page.confirmed || !page.reason.trim())) {
    throw new Error('Compare every source unit and record a review reason before saving.');
  }
  return {
    extractionRevision: record.extraction_revision,
    pages: drafts.map((page, index) => {
      const source = record.pages[index]!;
      const expected = source.blocks.filter((block) => block.status !== 'split').map((block) => block.id);
      const actual = page.blocks.map((block) => block.id);
      if (new Set(actual).size !== actual.length || actual.length !== expected.length || expected.some((id) => !actual.includes(id))) {
        throw new Error(`Unit ${page.number}: each source region must appear exactly once.`);
      }
      const blocks = page.blocks.map((block) => {
        const structure = JSON.parse(block.structureJson) as SourceStructure | null;
        if (!structure || typeof structure.text !== 'string' || !structure.complete || structure.uncertain || structure.text !== block.text) {
          throw new Error(`Region ${block.id}: structured JSON must be complete and match the source transcript.`);
        }
        return { id: block.id, selectedText: block.text, structure,
          relatedBlockIds: block.relatedIds.split(',').map((id) => id.trim()).filter(Boolean) };
      });
      return { number: page.number, selectedText: blocks.length ? blocks.map((block) => block.selectedText).join('\n') : page.text,
        reason: page.reason.trim(), structureConfirmed: true, blankConfirmed: page.blankConfirmed, blocks };
    }),
    issueResolutions: decisions.filter((decision) => {
      const issue = record.issues.find((item) => item.id === decision.id);
      if (!issue) throw new Error('Unknown issue decision. Reload the evidence.');
      if (issue.technical && decision.action !== 'unresolved') throw new Error('Technical extraction failures require reprocessing.');
      // Unchanged open issues stay open without a fabricated resolution reason.
      return decision.action !== 'unresolved' || Boolean(decision.reason.trim());
    }).map((decision) => {
      if (!decision.reason.trim()) throw new Error(`Issue ${decision.id}: enter a source-based reason.`);
      return { ...decision, reason: decision.reason.trim() };
    }),
  };
}
