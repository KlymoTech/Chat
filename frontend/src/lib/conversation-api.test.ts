import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  fallbackList: vi.fn(),
}));

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    api: {
      ...actual.api,
      conversations: {
        ...actual.api.conversations,
        list: mocks.fallbackList,
      },
    },
  };
});

vi.mock('@/lib/storage', () => ({
  readStorage: vi.fn(() => ({ accessToken: 'token-123' })),
}));

vi.mock('@/lib/workspace-api', () => ({
  activeWorkspaceId: vi.fn(() => 'workspace-1'),
}));

import { conversationApi } from '@/lib/conversation-api';

const emptyPage = { items: [], total: 0, page: 1, pageSize: 50 };

describe('conversationApi Education filters', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('keeps the existing generic conversation endpoint when Education scope is unused', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => emptyPage,
    });
    vi.stubGlobal('fetch', fetchMock);

    await conversationApi.list({ agentId: 'agent-1', channel: 'widget', state: 'open', search: 'Asha' });

    const [url, options] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain('/conversations?');
    expect(String(url)).not.toContain('/education/conversations');
    expect(String(url)).toContain('agent_id=agent-1');
    expect(String(url)).toContain('channel=widget');
    expect(String(url)).toContain('state=open');
    expect(String(url)).toContain('search=Asha');
    expect(options.headers).toMatchObject({
      Authorization: 'Bearer token-123',
      'X-Workspace-ID': 'workspace-1',
    });
  });

  it('keeps an Education Agent scoped even when no Course, Batch or Student is selected', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => emptyPage,
    });
    vi.stubGlobal('fetch', fetchMock);

    await conversationApi.list({ agentId: 'education-agent', educationScope: true });

    const [url] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain('/education/conversations?');
    expect(String(url)).toContain('agent_id=education-agent');
    expect(String(url)).not.toContain('course_id=');
    expect(String(url)).not.toContain('batch_id=');
    expect(String(url)).not.toContain('student_id=');
  });

  it('routes Course, Batch and Student filters through the Education conversation endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => emptyPage,
    });
    vi.stubGlobal('fetch', fetchMock);

    await conversationApi.list({
      agentId: 'agent-1',
      courseId: 'course-1',
      batchId: 'batch-1',
      studentId: 'student-1',
      state: 'resolved',
      pageSize: 25,
    });

    const [url] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain('/education/conversations?');
    expect(String(url)).toContain('agent_id=agent-1');
    expect(String(url)).toContain('course_id=course-1');
    expect(String(url)).toContain('batch_id=batch-1');
    expect(String(url)).toContain('student_id=student-1');
    expect(String(url)).toContain('state=resolved');
    expect(String(url)).toContain('page_size=25');
  });

  it('does not hide a real authorization error behind demo fallback', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({ detail: 'Forbidden' }),
    }));

    await expect(conversationApi.list({ courseId: 'course-1' })).rejects.toMatchObject({ status: 403 });
    expect(mocks.fallbackList).not.toHaveBeenCalled();
  });

  it('does not leak generic demo conversations when Education context cannot be loaded', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network unavailable')));
    mocks.fallbackList.mockResolvedValue({
      items: [{ id: 'generic-1' }], total: 1, page: 1, pageSize: 50,
    });

    const result = await conversationApi.list({ educationScope: true, agentId: 'education-agent' });

    expect(mocks.fallbackList).toHaveBeenCalledTimes(1);
    expect(result.items).toEqual([]);
    expect(result.total).toBe(0);
  });
});
