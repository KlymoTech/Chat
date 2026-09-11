import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PlatformAdminPage } from '@/pages/PlatformAdminPage';

const mocks = vi.hoisted(() => ({
  overview: vi.fn(),
  tenants: vi.fn(),
  tenant: vi.fn(),
}));

vi.mock('@/lib/platform-admin-api', () => ({
  platformAdminApi: {
    overview: mocks.overview,
    tenants: mocks.tenants,
    tenant: mocks.tenant,
  },
}));

const overview = {
  tenants: 2,
  workspaces: 4,
  users: 8,
  agents: 5,
  conversations: 120,
  leads: 18,
  subscriptions: { trial: 1, active: 1, pastDue: 0, suspended: 0, cancelled: 0 },
  operations: {
    status: 'degraded',
    failedIngestionJobs: 1,
    unpublishedOutboxEvents: 2,
    oldestUnpublishedEventAt: '2026-09-11T08:00:00Z',
    quarantinedEvents: 0,
    channelIssues: 1,
    crmConnectionIssues: 1,
    crmDeliveryIssues: 1,
    openCrmDeadLetters: 0,
    criticalAuditEvents24h: 0,
  },
};

const tenantSummary = {
  id: 'tenant-1',
  name: 'Northstar Academy',
  slug: 'northstar-academy',
  plan: 'professional',
  subscriptionStatus: 'active',
  workspaceCount: 2,
  memberCount: 4,
  agentCount: 3,
  conversationCount: 100,
  leadCount: 12,
  channelIssues: 1,
  crmIssues: 2,
  createdAt: '2026-09-01T00:00:00Z',
};

const tenantDetail = {
  ...tenantSummary,
  provider: null,
  currentPeriodEnd: null,
  cancelAtPeriodEnd: false,
  workspaces: [{
    id: 'workspace-1', name: 'Admissions', slug: 'admissions', status: 'active',
    memberCount: 4, agentCount: 3, conversationCount: 100, leadCount: 12,
    createdAt: '2026-09-01T00:00:00Z',
  }],
  recentAudit: [{
    id: 'audit-1', action: 'agent.updated', entityType: 'agent', entityId: 'agent-1',
    category: 'agent', severity: 'info', outcome: 'success', workspaceId: 'workspace-1',
    createdAt: '2026-09-11T09:00:00Z',
  }],
};

describe('PlatformAdminPage', () => {
  beforeEach(() => {
    mocks.overview.mockResolvedValue(overview);
    mocks.tenants.mockResolvedValue({ items: [tenantSummary], total: 1, limit: 50, offset: 0 });
    mocks.tenant.mockResolvedValue(tenantDetail);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('renders real platform, subscription, and operations data', async () => {
    render(<PlatformAdminPage />);

    expect(await screen.findByText('Control plane')).toBeInTheDocument();
    expect(screen.getByText('Operational issues')).toBeInTheDocument();
    expect(screen.getByText('Failed ingestion jobs')).toBeInTheDocument();
    expect(screen.getByText('CRM delivery issues')).toBeInTheDocument();
    expect(screen.getByText('Plans & subscriptions')).toBeInTheDocument();
    expect(screen.getByText('Northstar Academy')).toBeInTheDocument();
    expect(screen.getByText('Professional · Active')).toBeInTheDocument();
  });

  it('opens a tenant support view with workspace and audit metadata', async () => {
    const user = userEvent.setup();
    render(<PlatformAdminPage />);

    await user.click(await screen.findByRole('button', { name: /Northstar Academy/ }));
    await waitFor(() => expect(mocks.tenant).toHaveBeenCalledWith('tenant-1'));
    expect(await screen.findByText('Recent audit/support context')).toBeInTheDocument();
    expect(screen.getByText('Admissions')).toBeInTheDocument();
    expect(screen.getByText('agent.updated')).toBeInTheDocument();
  });

  it('searches tenants through the server query rather than filtering stale local data', async () => {
    const user = userEvent.setup();
    render(<PlatformAdminPage />);

    const input = await screen.findByRole('textbox', { name: 'Search tenants' });
    await user.type(input, 'CPA');
    await user.click(screen.getByRole('button', { name: 'Search' }));
    await waitFor(() => expect(mocks.tenants).toHaveBeenLastCalledWith('CPA'));
  });

  it('shows a safe denial state instead of rendering partial tenant data', async () => {
    mocks.overview.mockRejectedValueOnce(new Error('Platform administrator access required'));
    render(<PlatformAdminPage />);

    expect(await screen.findByText('Platform administrator access required')).toBeInTheDocument();
    expect(screen.queryByText('Tenant administration')).not.toBeInTheDocument();
  });
});
