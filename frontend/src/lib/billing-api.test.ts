import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { billingApi } from '@/lib/billing-api';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const subscription = {
  id: 'subscription-1',
  tenantId: 'tenant-1',
  plan: 'business',
  status: 'active',
  provider: null,
  trialEndsAt: null,
  currentPeriodStart: null,
  currentPeriodEnd: null,
  cancelAtPeriodEnd: false,
  pastDueAt: null,
  suspendedAt: null,
  cancelledAt: null,
  createdAt: '2026-09-11T00:00:00Z',
  updatedAt: '2026-09-11T00:00:00Z',
};

describe('billingApi', () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    localStorage.setItem('northstar.session', JSON.stringify({ accessToken: 'session-token' }));
    localStorage.setItem('northstar.active-workspace-id', JSON.stringify('workspace-1'));
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
    localStorage.clear();
  });

  it('loads the tenant subscription through the active authenticated workspace', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(subscription));

    const result = await billingApi.getSubscription('starter');

    expect(result).toEqual(subscription);
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/billing/subscription', expect.objectContaining({
      credentials: 'include',
      headers: expect.objectContaining({
        Authorization: 'Bearer session-token',
        'X-Workspace-ID': 'workspace-1',
      }),
    }));
  });

  it('does not hide authorization errors behind demo subscription state', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: { message: 'Insufficient permission' } }, 403));

    await expect(billingApi.getSubscription('starter')).rejects.toThrow('Insufficient permission');
  });

  it('preserves offline/demo billing behavior when the backend is unavailable', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Network unavailable'));

    const result = await billingApi.getSubscription('business');

    expect(result.plan).toBe('business');
    expect(result.status).toBe('active');
    expect(result.id).toBe('subscription-demo');
  });
});
