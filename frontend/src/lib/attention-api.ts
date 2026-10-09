import { api, request } from '@/lib/api';
import type { Conversation, PageResult } from '@/types';

const LIMIT = 3;
const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === 'true';

/** Filter on the server BEFORE pagination: recent resolved chats must not hide work. */
export async function loadAttentionConversations(): Promise<PageResult<Conversation>> {
  const pages = DEMO_MODE
    ? [await api.conversations.list()]
    : await Promise.all((['open', 'escalated'] as const).map((state) =>
      request<PageResult<Conversation>>(`/conversations?state=${state}&page=1&page_size=${LIMIT}`),
    ));
  const unique = new Map<string, Conversation>();
  for (const page of pages) {
    for (const item of page.items) {
      if (item.state === 'resolved') continue;
      const previous = unique.get(item.id);
      if (!previous || Date.parse(item.updatedAt) > Date.parse(previous.updatedAt)) {
        unique.set(item.id, item);
      }
    }
  }
  const items = [...unique.values()].sort((a, b) =>
    Date.parse(b.updatedAt) - Date.parse(a.updatedAt) || a.id.localeCompare(b.id),
  );
  // Separate requests are not a transactional snapshot. The card shows records,
  // not this total; never turn a partial request failure into an empty queue.
  return {
    items: items.slice(0, LIMIT),
    total: DEMO_MODE ? items.length : pages.reduce((sum, page) => sum + page.total, 0),
    page: 1,
    pageSize: LIMIT,
  };
}
