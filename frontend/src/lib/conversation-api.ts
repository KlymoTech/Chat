import { api, ApiError } from '@/lib/api';
import { readStorage } from '@/lib/storage';
import { activeWorkspaceId } from '@/lib/workspace-api';
import type { Conversation, ConversationState, PageResult, Session } from '@/types';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const DEMO_MODE = (import.meta.env.VITE_DEMO_MODE as string | undefined) !== 'false';
const SESSION_KEY = 'northstar.session';

export interface ConversationFilters {
  agentId?: string;
  channel?: string;
  state?: ConversationState;
  search?: string;
  page?: number;
  pageSize?: number;
}

function authHeaders(): HeadersInit {
  const session = readStorage<Session | null>(SESSION_KEY, null);
  const workspaceId = activeWorkspaceId();
  return {
    Accept: 'application/json',
    ...(session ? { Authorization: `Bearer ${session.accessToken}` } : {}),
    ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
  };
}

function matchesFallback(item: Conversation, filters: ConversationFilters): boolean {
  const query = filters.search?.trim().toLowerCase();
  return (
    (!filters.agentId || item.agentId === filters.agentId)
    && (!filters.channel || item.channel === filters.channel)
    && (!filters.state || item.state === filters.state)
    && (!query || `${item.visitorName} ${item.visitorEmail ?? ''} ${item.preview}`.toLowerCase().includes(query))
  );
}

export const conversationApi = {
  async list(filters: ConversationFilters = {}): Promise<PageResult<Conversation>> {
    const params = new URLSearchParams();
    if (filters.agentId) params.set('agent_id', filters.agentId);
    if (filters.channel) params.set('channel', filters.channel);
    if (filters.state) params.set('state', filters.state);
    if (filters.search?.trim()) params.set('search', filters.search.trim());
    params.set('page', String(filters.page ?? 1));
    params.set('page_size', String(filters.pageSize ?? 50));
    try {
      const response = await fetch(`${API_URL}/conversations?${params.toString()}`, {
        credentials: 'include',
        headers: authHeaders(),
      });
      if (!response.ok) throw new ApiError(`Conversation request failed (${response.status})`, response.status);
      return response.json() as Promise<PageResult<Conversation>>;
    } catch (error) {
      if (!DEMO_MODE || (error instanceof ApiError && [400, 401, 403, 409, 422].includes(error.status))) throw error;
      const fallback = await api.conversations.list();
      const items = fallback.items.filter((item) => matchesFallback(item, filters));
      const page = filters.page ?? 1;
      const pageSize = filters.pageSize ?? 50;
      const start = (page - 1) * pageSize;
      return { ...fallback, items: items.slice(start, start + pageSize), total: items.length, page, pageSize };
    }
  },

  async resolve(conversationId: string): Promise<Conversation> {
    const response = await fetch(`${API_URL}/conversations/${conversationId}/resolve`, {
      method: 'POST',
      credentials: 'include',
      headers: authHeaders(),
    });
    if (!response.ok) throw new ApiError(`Conversation resolve failed (${response.status})`, response.status);
    return response.json() as Promise<Conversation>;
  },
};
