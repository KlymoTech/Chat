import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { platformAdminApi } from '@/lib/platform-admin-api';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('platformAdminApi', () => {
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

  it('checks access without exposing authorization failures to normal navigation', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: { message: 'Platform administrator access required' } }, 403));
    await expect(platformAdminApi.canAccess()).resolves.toBe(false);

    fetchMock.mockResolvedValueOnce(jsonResponse({ authorized: true, email: 'admin@example.com' }));
    await expect(platformAdminApi.canAccess()).resolves.toBe(true);
  });

  it('loads authenticated workspace-aware overview and tenant search', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({
      tenants: 2,
      workspaces: 3,
      users: 4,
      agents: 5,
      conversations: 6,
      leads: 7,
      subscriptions: { trial: 0, active: 2, pastDue: 0, suspended: 0, cancelled: 0 },
      operations: {
        status: 'healthy', failedIngestionJobs: 0, unpublishedOutboxEvents: 0,
        oldestUnpublishedEventAt: null, quarantinedEvents: 0, channelIssues: 0,
        crmConnectionIssues: 0, crmDeliveryIssues: 0, openCrmDeadLetters: 0,
        criticalAuditEvents24h: 0,
      },
    }));
    const overview = await platformAdminApi.overview();
    expect(overview.tenants).toBe(2);
    expect(fetchMock).toHaveBeenLastCalledWith('/api/v1/platform-admin/overview', expect.objectContaining({
      credentials: 'include',
      headers: expect.objectContaining({
        Authorization: 'Bearer session-token',
      }),
    }));
    expect(fetchMock.mock.calls[0]?.[1]?.headers).not.toHaveProperty('X-Workspace-ID');

    fetchMock.mockResolvedValueOnce(jsonResponse({ items: [], total: 0, limit: 50, offset: 0 }));
    await platformAdminApi.tenants('North Star');
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/v1/platform-admin/tenants?limit=50&offset=0&search=North+Star',
      expect.any(Object),
    );
  });

  it('surfaces server and network failures for control-plane data', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: { message: 'Access denied' } }, 403));
    await expect(platformAdminApi.overview()).rejects.toThrow('Access denied');

    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'source desired state is stale' }, 409));
    await expect(platformAdminApi.runtimeSpec()).rejects.toThrow('source desired state is stale');

    fetchMock.mockRejectedValueOnce(new TypeError('Network unavailable'));
    await expect(platformAdminApi.tenants()).rejects.toThrow('Network unavailable');
  });

  it('loads server-owned platform capabilities without workspace scoping', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({
      email: 'support@example.com',
      permissions: ['platform.tenants.read', 'platform.support.impersonate'],
    }));
    await expect(platformAdminApi.permissions()).resolves.toEqual({
      email: 'support@example.com',
      permissions: ['platform.tenants.read', 'platform.support.impersonate'],
    });
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/v1/platform-admin/permissions',
      expect.objectContaining({ credentials: 'include' }),
    );
  });


  it('plans capability changes before creating them and never uses a direct apply endpoint', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({
      capability_id: 'cache',
      operation: 'disable',
      policy: {
        capability_id: 'cache', risk_class: 'blue', switch_class: 'application-provider',
        mutable: true, allowed_operations: ['disable'], production_approval_required: true,
        destructive_requires_gitops: true,
      },
      environment_policy: {
        environment: 'production', distinct_approver_required: true,
        destructive_requires_gitops: true, allow_direct_runtime_flags: false,
        stabilization_seconds: 300,
      },
      current: {},
      desired: {},
      analysis: {
        plan: {
          plan_id: 'plan-1', action: 'restart', classification: 'restart',
          source_revision: 4, target_revision: 5, source_digest: 'a'.repeat(64),
          target_digest: 'b'.repeat(64), requires_approval: true, destructive: false,
          steps: ['validate_dependencies'], blockers: [], created_at: new Date().toISOString(),
        },
        changed_capabilities: ['cache'], impacted_capabilities: ['cache'], blockers: [],
      },
    }));
    const plan = await platformAdminApi.planRuntimeCapabilityChange('cache', { operation: 'disable' });
    expect(plan.analysis.plan.requires_approval).toBe(true);
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/v1/platform-admin/runtime/capabilities/cache/plan',
      expect.objectContaining({ method: 'POST' }),
    );

    fetchMock.mockResolvedValueOnce(jsonResponse({
      id: 'change-1', environment: 'production', requested_by: 'user-1', approved_by: null,
      status: 'waiting_approval', action: 'restart', classification: 'restart', operation: 'disable',
      requires_approval: true, destructive: false, source_revision: 4, target_revision: 5,
      source_digest: 'a'.repeat(64), target_digest: 'b'.repeat(64),
      idempotency_key: 'control-1', reason: 'Disable cache safely', plan_steps: [],
      blockers: [], changed_capabilities: ['cache'], impacted_capabilities: ['cache'],
      requested_at: new Date().toISOString(), approved_at: null,
    }), 201));
    await platformAdminApi.createRuntimeCapabilityChange('cache', {
      operation: 'disable',
      reason: 'Disable cache safely',
      idempotency_key: 'control-1',
    });
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/v1/platform-admin/runtime/capabilities/cache/changes',
      expect.objectContaining({ method: 'POST' }),
    );
    expect(fetchMock.mock.calls.flatMap((call) => [String(call[0])]).some((url) => url.endsWith('/apply'))).toBe(false);
  });

  it('uses a reviewed rollback endpoint with an idempotency key', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({
      id: 'rollback-1', environment: 'staging', requested_by: 'user-1', approved_by: null,
      status: 'waiting_approval', action: 'restart', classification: 'restart', operation: 'switch',
      requires_approval: true, destructive: false, source_revision: 8, target_revision: 9,
      source_digest: 'a'.repeat(64), target_digest: 'b'.repeat(64), idempotency_key: 'rollback-key',
      reason: 'Rollback failed deployment', plan_steps: [], blockers: [], changed_capabilities: [],
      impacted_capabilities: [], requested_at: new Date().toISOString(), approved_at: null,
    }), 201));

    await platformAdminApi.rollbackRuntimeChange('change-8', {
      reason: 'Rollback failed deployment',
      idempotency_key: 'rollback-key',
    });

    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/v1/platform-admin/runtime/changes/change-8/rollback',
      expect.objectContaining({ method: 'POST' }),
    );
  });
});
