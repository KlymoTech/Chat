import type { Session } from '@/types';
import { activeWorkspaceId } from '@/lib/workspace-api';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

export type CRMDeadLetterStatus = 'open' | 'resolved' | 'all';

export interface CRMDeadLetterView {
  id: string;
  delivery_id: string;
  lead_id: string;
  connection_id: string;
  provider: string;
  status: string;
  reason_code?: string | null;
  reason_message?: string | null;
  created_at: string;
  updated_at: string;
  resolved_at?: string | null;
}

function currentSession(): Session | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? JSON.parse(raw) as Session : null;
  } catch {
    return null;
  }
}

async function call<T>(path: string): Promise<T> {
  const active = currentSession();
  const workspaceId = activeWorkspaceId();
  const response = await fetch(`${API_URL}${path}`, {
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...(active ? { Authorization: `Bearer ${active.accessToken}` } : {}),
      ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
    },
  });
  if (!response.ok) {
    const body = await response.text().catch(() => '');
    throw new Error(body || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const crmDeadLetterApi = {
  list: (filters: { status?: CRMDeadLetterStatus; connectionId?: string } = {}) => {
    const params = new URLSearchParams();
    if (filters.status) params.set('status', filters.status);
    if (filters.connectionId) params.set('connection_id', filters.connectionId);
    const query = params.toString();
    return call<CRMDeadLetterView[]>(`/crm/dead-letters${query ? `?${query}` : ''}`);
  },
};
