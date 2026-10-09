import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadAttentionConversations } from './attention-api';
import { clearActiveWorkspaceSelection, persistActiveWorkspace } from './workspace-api';
import type { Conversation } from '@/types';

function item(id: string, state: Conversation['state'], minute: number): Conversation {
  return {
    id, state, agentId: 'agent-a', workspaceId: 'workspace-a', visitorName: id,
    channel: 'widget', sentiment: 'neutral', preview: 'Needs a reply', unread: 0,
    messages: [], startedAt: '2026-10-08T10:00:00Z',
    updatedAt: `2026-10-08T10:${String(minute).padStart(2, '0')}:00Z`,
  };
}
function page(items: Conversation[], total = items.length) {
  return new Response(JSON.stringify({ items, total, page: 1, pageSize: 3 }), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  });
}

beforeEach(() => {
  localStorage.setItem('northstar.session', JSON.stringify({
    accessToken: 'real-test-access-token', user: { id: 'owner', role: 'owner' },
  }));
  persistActiveWorkspace('workspace-a');
});
afterEach(() => { clearActiveWorkspaceSelection(); vi.unstubAllGlobals(); });

describe('attention queue uses the authenticated backend contract', () => {
  it('queries each unresolved state before pagination and merges the newest three', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(page([
      item('open-1', 'open', 10), item('open-2', 'open', 8), item('open-3', 'open', 2),
    ], 25)).mockResolvedValueOnce(page([
      item('escalated-1', 'escalated', 12), item('escalated-2', 'escalated', 9),
    ], 7));
    vi.stubGlobal('fetch', fetchMock);
    const result = await loadAttentionConversations();
    expect(result.items.map((entry) => entry.id)).toEqual(['escalated-1', 'open-1', 'escalated-2']);
    expect(result.total).toBe(32);
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/v1/conversations?state=open&page=1&page_size=3',
      '/api/v1/conversations?state=escalated&page=1&page_size=3',
    ]);
    for (const [, options] of fetchMock.mock.calls) {
      const init = options as RequestInit;
      expect(init.credentials).toBe('include');
      const headers = new Headers(init.headers);
      expect(headers.get('Authorization')).toBe('Bearer real-test-access-token');
      expect(headers.get('X-Workspace-ID')).toBe('workspace-a');
    }
  });

  it('deduplicates a conversation whose state changed between requests', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(page([item('same', 'open', 10)]))
      .mockResolvedValueOnce(page([item('same', 'escalated', 12)])));
    expect((await loadAttentionConversations()).items).toEqual([item('same', 'escalated', 12)]);
  });

  it('does not disguise partial outages or permission failures as an empty queue', async () => {
    for (const status of [403, 503]) {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(page([])).mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: 'Unavailable' }), { status }),
      ));
      await expect(loadAttentionConversations()).rejects.toMatchObject({ status });
    }
  });

  it('returns a genuinely empty queue only when both filtered requests succeed', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(page([]))));
    await expect(loadAttentionConversations()).resolves.toEqual({ items: [], total: 0, page: 1, pageSize: 3 });
  });

  it('uses the newly selected workspace for both requests', async () => {
    persistActiveWorkspace('workspace-b');
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(page([])));
    vi.stubGlobal('fetch', fetchMock);
    await loadAttentionConversations();
    for (const [, init] of fetchMock.mock.calls) {
      expect(new Headers((init as RequestInit).headers).get('X-Workspace-ID')).toBe('workspace-b');
    }
  });
});
