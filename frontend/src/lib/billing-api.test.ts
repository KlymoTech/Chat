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

const entitlements = {
  plan: 'business',
  subscriptionStatus: 'active',
  limits: {
    workspaces: 10,
    agents: 10,
    members: 20,
    conversationsMonthly: 5000,
    tokensMonthly: 5_000_000,
    storageBytes: 20 * 1024 ** 3,
  },
  usage: {
    workspaces: 2,
    agents: 4,
    members: 6,
    pendingMemberSeats: 1,
    conversationsMonthly: 100,
    tokensMonthly: 20_000,
    storageBytes: 1024,
  },
  features: {
    allowedChannels: ['widget', 'api', 'whatsapp'],
    crm: true,
    api: true,
    whiteLabel: true,
  },
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

  it('loads subscription and entitlements through the active authenticated workspace', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(subscription));
    const subscriptionResult = await billingApi.getSubscription('starter');
    expect(subscriptionResult).toEqual(subscription);
    expect(fetchMock).toHaveBeenLastCalledWith('/api/v1/billing/subscription', expect.objectContaining({
      credentials: 'include',
      headers: expect.objectContaining({
        Authorization: 'Bearer session-token',
        'X-Workspace-ID': 'workspace-1',
      }),
    }));

    fetchMock.mockResolvedValueOnce(jsonResponse(entitlements));
    const entitlementResult = await billingApi.getEntitlements('starter');
    expect(entitlementResult).toEqual(entitlements);
    expect(fetchMock).toHaveBeenLastCalledWith('/api/v1/billing/entitlements', expect.objectContaining({
      credentials: 'include',
      headers: expect.objectContaining({ Authorization: 'Bearer session-token' }),
    }));
  });

  it('does not hide authorization errors behind demo billing state', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: { message: 'Insufficient permission' } }, 403));
    await expect(billingApi.getSubscription('starter')).rejects.toThrow('Insufficient permission');

    fetchMock.mockResolvedValueOnce(jsonResponse({ error: { message: 'Insufficient permission' } }, 403));
    await expect(billingApi.getEntitlements('starter')).rejects.toThrow('Insufficient permission');
  });

  it('preserves offline/demo billing and entitlement behavior when the backend is unavailable', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Network unavailable'));
    const subscriptionResult = await billingApi.getSubscription('business');
    expect(subscriptionResult.plan).toBe('business');
    expect(subscriptionResult.status).toBe('active');
    expect(subscriptionResult.id).toBe('subscription-demo');

    fetchMock.mockRejectedValueOnce(new TypeError('Network unavailable'));
    const entitlementResult = await billingApi.getEntitlements('business');
    expect(entitlementResult.plan).toBe('business');
    expect(entitlementResult.limits.agents).toBe(10);
    expect(entitlementResult.limits.members).toBe(20);
    expect(entitlementResult.limits.conversationsMonthly).toBe(5000);
    expect(entitlementResult.features.allowedChannels).toContain('whatsapp');
  });

  it('keeps unknown legacy plans unlimited in offline fallback mode', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Network unavailable'));
    const result = await billingApi.getEntitlements('legacy_custom_contract');

    expect(result.plan).toBe('legacy_custom_contract');
    expect(result.limits.workspaces).toBeNull();
    expect(result.limits.agents).toBeNull();
    expect(result.limits.members).toBeNull();
    expect(result.features.crm).toBe(true);
    expect(result.features.whiteLabel).toBe(true);
    expect(result.features.allowedChannels).toContain('whatsapp');
  });
});
