import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/lib/api';
import { helpApi } from '@/lib/help-api';
import { clearActiveWorkspaceSelection, persistActiveWorkspace } from '@/lib/workspace-api';
import type { Session } from '@/types';

const jsonResponse = (value: unknown): Response => new Response(JSON.stringify(value), {
  status: 200,
  headers: { 'Content-Type': 'application/json' },
});

function savedSession(accessToken: string, refreshToken?: string): Session {
  return {
    accessToken,
    ...(refreshToken ? { refreshToken } : {}),
    expiresAt: '2026-12-01T00:00:00Z',
    user: { id: 'user-1', name: 'Workspace Owner', email: 'owner@example.com', role: 'owner' },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  clearActiveWorkspaceSelection();
  localStorage.clear();
});

describe('Help Center shared API authentication', () => {
  it('shares exactly one token refresh with another API feature under concurrent 401 responses', async () => {
    const expired = savedSession('expired-access', 'refresh-one');
    const rotated = savedSession('fresh-access', 'refresh-two');
    localStorage.setItem('northstar.session', JSON.stringify(expired));
    persistActiveWorkspace('workspace-1');

    let releaseRefresh: (() => void) | undefined;
    const refreshGate = new Promise<void>((resolve) => { releaseRefresh = resolve; });
    let refreshCalls = 0;
    let resourceCalls = 0;

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/auth/refresh')) {
        refreshCalls += 1;
        await refreshGate;
        return jsonResponse(rotated);
      }
      resourceCalls += 1;
      if (resourceCalls <= 2) return new Response(null, { status: 401 });
      expect(init?.headers).toEqual(expect.objectContaining({
        Authorization: 'Bearer fresh-access',
        'X-Workspace-ID': 'workspace-1',
      }));
      return jsonResponse([]);
    });
    vi.stubGlobal('fetch', fetchMock);

    const help = helpApi.categories();
    const agents = api.agents.list();
    await vi.waitFor(() => {
      expect(resourceCalls).toBe(2);
      expect(refreshCalls).toBe(1);
    });
    releaseRefresh?.();

    await expect(Promise.all([help, agents])).resolves.toEqual([[], []]);
    expect(refreshCalls).toBe(1);
    expect(resourceCalls).toBe(4);
    expect(api.auth.session()?.accessToken).toBe('fresh-access');
    expect(api.auth.session()?.refreshToken).toBeUndefined();
  });

  it('preserves workspace authorization and returns undefined for Help event 204 responses', async () => {
    localStorage.setItem('northstar.session', JSON.stringify(savedSession('active-access')));
    persistActiveWorkspace('workspace-2');
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(helpApi.event('search_click', 'article-1', 'setup')).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/help/events', expect.objectContaining({
      credentials: 'include',
      method: 'POST',
      body: JSON.stringify({ eventType: 'search_click', articleId: 'article-1', query: 'setup' }),
      headers: expect.objectContaining({
        Authorization: 'Bearer active-access',
        'X-Workspace-ID': 'workspace-2',
      }),
    }));
  });

  it('preserves a plain-text upstream error without consuming the response twice', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('Help service is unavailable', {
      status: 502,
      headers: { 'Content-Type': 'text/plain' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(helpApi.home()).rejects.toMatchObject({
      name: 'ApiError',
      status: 502,
      detail: 'Help service is unavailable',
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('clears expired browser credentials when a Help request refresh is rejected', async () => {
    localStorage.setItem('northstar.session', JSON.stringify(savedSession('expired-access', 'invalid-refresh')));
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(new Response(null, { status: 401 }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(helpApi.categories()).rejects.toMatchObject({ status: 401, name: 'ApiError' });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(api.auth.session()).toBeNull();
  });
});
