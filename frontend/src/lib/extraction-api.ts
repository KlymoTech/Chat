import { api, ApiError } from '@/lib/api';
import { activeWorkspaceId } from '@/lib/workspace-api';
import type { KnowledgeSource } from '@/types';

export interface SourceReading {
  kind: string;
  text: string;
  complete: boolean;
  uncertain?: boolean;
  blank?: boolean;
  [key: string]: unknown;
}
export interface SourceBlock {
  id: string;
  type: string;
  status: string;
  native_text?: string;
  selected_text: string | null;
  visual?: SourceReading | null;
  reviewed_structure?: SourceReading | null;
  related_block_ids?: string[];
  bbox_px?: number[];
  parent_id?: string | null;
}
export interface SourcePage {
  number: number;
  source_unit?: string;
  source_page_number?: number | null;
  rendered_page_number?: number | null;
  native_text: string;
  visual_text: string | null;
  selected_text: string | null;
  image: string | null;
  requires_image?: boolean;
  requires_second_review?: boolean;
  blocks: SourceBlock[];
  primary_review?: { reviewer: string };
  second_review?: { reviewer: string };
}
export interface SourceIssue {
  id: string;
  page: number;
  block_id?: string | null;
  code: string;
  message: string;
  technical?: boolean;
  status?: string;
  disposition?: 'source_verified' | 'source_anomaly' | 'unresolved';
  resolution_reason?: string;
}
export interface SourceRecord {
  schema_version: number;
  extraction_revision: number | null;
  source_sha256: string;
  review_status: string;
  release_eligible?: boolean;
  release_blockers?: string[];
  pages: SourcePage[];
  issues: SourceIssue[];
  checks?: Array<{ name: string; status: string; details?: string[] }>;
  metrics?: { measured_transcription_accuracy?: string };
  word?: { blocks: Array<{ id: string; text: string; type: string; part: string; mapping_status: string; rendered_pages: number[] }> };
}
export interface ReviewPageInput {
  number: number;
  selectedText: string;
  reason: string;
  structureConfirmed: boolean;
  blankConfirmed: boolean;
  blocks: Array<{ id: string; selectedText: string; structure: SourceReading; relatedBlockIds: string[] }>;
}
export interface ReviewInput {
  extractionRevision: number;
  pages: ReviewPageInput[];
  issueResolutions: Array<{ id: string; action: 'source_verified' | 'source_anomaly' | 'unresolved'; reason: string }>;
}

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';

async function approve(sourceId: string, input: ReviewInput, workspaceId = activeWorkspaceId(), retried = false): Promise<KnowledgeSource> {
  if (workspaceId !== activeWorkspaceId()) throw new ApiError('Workspace changed. Reopen the review.', 409);
  const session = api.auth.session();
  const response = await fetch(`${API_URL}/knowledge/${encodeURIComponent(sourceId)}/extraction/approve`, {
    method: 'POST', credentials: 'include',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json',
      ...(session ? { Authorization: `Bearer ${session.accessToken}` } : {}),
      ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
    },
    body: JSON.stringify(input),
  });
  if (response.status === 401 && session && !retried) {
    // Reuse the central client's single-flight refresh instead of maintaining a second refresh token.
    await api.knowledge.extraction(sourceId);
    return approve(sourceId, input, workspaceId, true);
  }
  if (!response.ok) {
    const raw = await response.text();
    let detail: unknown = raw;
    try { detail = JSON.parse(raw) as unknown; } catch { /* Keep a readable proxy error. */ }
    throw new ApiError(`Review request failed (${response.status})`, response.status, detail);
  }
  return response.json() as Promise<KnowledgeSource>;
}

export const extractionApi = {
  async load(sourceId: string): Promise<SourceRecord> {
    const value = await api.knowledge.extraction(sourceId) as unknown as SourceRecord;
    if (value.schema_version !== 2 || !Array.isArray(value.pages) || !Array.isArray(value.issues)) {
      throw new ApiError('This extraction needs to be retried with the current evidence schema.', 409);
    }
    return value;
  },
  approve,
};
