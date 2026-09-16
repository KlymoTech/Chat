import { api, ApiError } from '@/lib/api';
import { activeWorkspaceId } from '@/lib/workspace-api';
import type { KnowledgeSource } from '@/types';
import type { EvidenceRecord, buildApproval } from './extraction-review-contract';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';

export async function loadExtraction(sourceId: string): Promise<EvidenceRecord> {
  const value = await api.knowledge.extraction(sourceId) as unknown as EvidenceRecord;
  if (value.schema_version !== 2 || !Array.isArray(value.pages)) throw new Error('Retry extraction to create current source evidence.');
  return value;
}

export async function submitExtractionReview(sourceId: string, payload: ReturnType<typeof buildApproval>): Promise<KnowledgeSource> {
  const workspace = activeWorkspaceId();
  for (let attempt = 0; attempt < 2; attempt += 1) {
    if (workspace !== activeWorkspaceId()) throw new ApiError('Workspace changed. Reopen the review.', 409);
    const session = api.auth.session();
    const response = await fetch(`${API_URL}/knowledge/${encodeURIComponent(sourceId)}/extraction/approve`, {
      method: 'POST', credentials: 'include',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json',
        ...(session ? { Authorization: `Bearer ${session.accessToken}` } : {}),
        ...(workspace ? { 'X-Workspace-ID': workspace } : {}) },
      body: JSON.stringify(payload),
    });
    if (response.status === 401 && attempt === 0) {
      // Reuse the existing client's single-flight refresh. Never adopt a newer
      // evidence revision silently: the original payload still receives 409.
      await api.knowledge.extraction(sourceId);
      continue;
    }
    if (!response.ok) {
      let detail: unknown;
      const text = await response.text();
      try { detail = JSON.parse(text) as unknown; } catch { detail = text; }
      throw new ApiError(response.status === 409 ? 'Evidence changed. Reload before reviewing.' : `Review failed (${response.status})`, response.status, detail);
    }
    return await response.json() as KnowledgeSource;
  }
  throw new ApiError('Sign in again to submit this review.', 401);
}
