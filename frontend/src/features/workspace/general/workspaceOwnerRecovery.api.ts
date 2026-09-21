import { readStorage } from '@/lib/storage';
import { activeWorkspaceId, workspacePresentationKey } from '@/lib/workspace-api';
import type { WorkspaceOwner } from '@/lib/workspace-api';

export type WorkspaceRecoveryReason = 'recorded_owner_unavailable' | 'legacy_owner_unavailable';
export interface WorkspaceOwnerRecoveryInput {
  targetUserId: string;
  confirmation: 'RECOVER';
  reason: WorkspaceRecoveryReason;
}

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';

/** Never use the demo fallback, silently retry a write, or change workspace on recovery. */
export async function recoverWorkspaceOwner(input: WorkspaceOwnerRecoveryInput): Promise<WorkspaceOwner> {
  const identity = workspacePresentationKey();
  const workspaceId = activeWorkspaceId();
  const token = readStorage<{ accessToken?: string } | null>('northstar.session', null)?.accessToken;
  if (!workspaceId || !token) throw new Error('Select a workspace and sign in before recovery');
  const checkContext = () => {
    if (identity !== workspacePresentationKey() || workspaceId !== activeWorkspaceId()
      || token !== readStorage<{ accessToken?: string } | null>('northstar.session', null)?.accessToken) {
      throw new DOMException('Account or workspace changed. Reload to verify the outcome before retrying.', 'AbortError');
    }
  };
  checkContext();
  const response = await fetch(`${API_URL}/workspace/owner/recover`, {
    method: 'POST', credentials: 'include', cache: 'no-store',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`, 'X-Workspace-ID': workspaceId },
    body: JSON.stringify(input),
  });
  checkContext();
  const payload: unknown = await response.json().catch(() => null);
  checkContext();
  if (!response.ok) {
    const error = payload as { detail?: unknown; error?: { message?: string } } | null;
    throw new Error(error?.error?.message
      ?? (typeof error?.detail === 'string' ? error.detail : `Owner recovery failed (${response.status})`));
  }
  if (!payload || typeof payload !== 'object' || !('ownerUserId' in payload)
    || typeof payload.ownerUserId !== 'string') {
    throw new Error('Owner recovery response was invalid; reload to check ownership');
  }
  return payload as WorkspaceOwner;
}
