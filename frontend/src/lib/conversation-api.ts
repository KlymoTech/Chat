import { api, ApiError } from '@/lib/api';
import { readStorage } from '@/lib/storage';
import { activeWorkspaceId } from '@/lib/workspace-api';
import type { Conversation, ConversationState, PageResult, Session } from '@/types';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const DEMO_MODE = (import.meta.env.VITE_DEMO_MODE as string | undefined) !== 'false';
const SESSION_KEY = 'northstar.session';

export interface ConversationFilters {
  agentId?: string;
  educationScope?: boolean;
  courseId?: string;
  batchId?: string;
  studentId?: string;
  channel?: string;
  state?: ConversationState;
  search?: string;
  page?: number;
  pageSize?: number;
}

export interface EducationUpsellResolution {
  conversationId: string;
  state: ConversationState;
  leadId: string;
  leadCreated: boolean;
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

function usesEducationScope(filters: ConversationFilters): boolean {
  return Boolean(filters.educationScope || filters.courseId || filters.batchId || filters.studentId);
}

export const conversationApi = {
  async list(filters: ConversationFilters = {}): Promise<PageResult<Conversation>> {
    const params = new URLSearchParams();
    if (filters.agentId) params.set('agent_id', filters.agentId);
    if (filters.courseId) params.set('course_id', filters.courseId);
    if (filters.batchId) params.set('batch_id', filters.batchId);
    if (filters.studentId) params.set('student_id', filters.studentId);
    if (filters.channel) params.set('channel', filters.channel);
    if (filters.state) params.set('state', filters.state);
    if (filters.search?.trim()) params.set('search', filters.search.trim());
    params.set('page', String(filters.page ?? 1));
    params.set('page_size', String(filters.pageSize ?? 50));
    const educationScoped = usesEducationScope(filters);
    const endpoint = educationScoped ? '/education/conversations' : '/conversations';
    try {
      const response = await fetch(`${API_URL}${endpoint}?${params.toString()}`, {
        credentials: 'include',
        headers: authHeaders(),
      });
      if (!response.ok) throw new ApiError(`Conversation request failed (${response.status})`, response.status);
      return response.json() as Promise<PageResult<Conversation>>;
    } catch (error) {
      if (!DEMO_MODE || (error instanceof ApiError && [400, 401, 403, 409, 422].includes(error.status))) throw error;
      const fallback = await api.conversations.list();
      const page = filters.page ?? 1;
      const pageSize = filters.pageSize ?? 50;
      if (educationScoped) {
        // Demo conversations do not carry immutable EducationConversationContext.
        // Returning generic conversations here would falsely bypass Education authorization scope.
        return { ...fallback, items: [], total: 0, page, pageSize };
      }
      const items = fallback.items.filter((item) => matchesFallback(item, filters));
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

  async resolveEducationSalesIntent(conversationId: string): Promise<EducationUpsellResolution> {
    const response = await fetch(
      `${API_URL}/education/conversations/${conversationId}/resolve-sales-intent`,
      {
        method: 'POST',
        credentials: 'include',
        headers: authHeaders(),
      },
    );
    if (!response.ok) {
      const payload = await response.json().catch(() => null) as { error?: { message?: string } } | null;
      throw new ApiError(
        payload?.error?.message ?? `Education sales-intent resolve failed (${response.status})`,
        response.status,
      );
    }
    return response.json() as Promise<EducationUpsellResolution>;
  },
};
