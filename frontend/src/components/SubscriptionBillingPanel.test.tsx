import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SubscriptionBillingPanel } from '@/components/SubscriptionBillingPanel';
import type { WorkspaceSettings } from '@/lib/workspace-api';

const mocks = vi.hoisted(() => ({
  pushToast: vi.fn(),
  getSubscription: vi.fn(),
  getEntitlements: vi.fn(),
}));

vi.mock('@/components/providers', () => ({
  useToast: () => ({ pushToast: mocks.pushToast }),
}));

vi.mock('@/lib/billing-api', () => ({
  billingApi: {
    getSubscription: mocks.getSubscription,
    getEntitlements: mocks.getEntitlements,
  },
}));

const workspace: WorkspaceSettings = {
  id: 'workspace-1',
  tenantId: 'tenant-1',
  tenantName: 'Northstar Academy',
  name: 'Admissions',
  slug: 'admissions',
  status: 'active',
  role: 'workspace_admin',
  permissions: ['*'],
  plan: 'starter',
  memberCount: 4,
  preferences: {
    timezone: 'Asia/Calcutta',
    defaultLanguage: 'English',
    dateFormat: 'DD/MM/YYYY',
  },
  whiteLabel: {
    companyName: 'Northstar Academy',
    logoDataUrl: '',
    faviconDataUrl: '',
    appIconDataUrl: '',
    primaryColor: '#146cf6',
    secondaryColor: '#705cf6',
    supportEmail: 'support@example.com',
    supportUrl: 'https://example.com/support',
    browserTitle: 'Northstar',
    customDomain: '',
    dnsStatus: 'not-configured',
    brandedLogin: true,
    brandedDashboard: true,
    brandedWidget: true,
    brandedEmails: true,
    removePlatformBranding: false,
  },
};

const subscription = {
  id: 'subscription-1',
  tenantId: 'tenant-1',
  plan: 'professional',
  status: 'trial',
  provider: null,
  trialEndsAt: '2026-09-25T00:00:00Z',
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
  plan: 'professional',
  subscriptionStatus: 'trial',
  limits: {
    workspaces: 3,
    agents: 5,
    members: 10,
    conversationsMonthly: 3000,
    tokensMonthly: 2_000_000,
    storageBytes: 5 * 1024 ** 3,
  },
  usage: {
    workspaces: 2,
    agents: 4,
    members: 7,
    pendingMemberSeats: 1,
    conversationsMonthly: 1200,
    tokensMonthly: 450_000,
    storageBytes: 1024 ** 3,
  },
  features: {
    allowedChannels: ['widget', 'api', 'whatsapp'],
    crm: true,
    api: true,
    whiteLabel: false,
  },
};

describe('SubscriptionBillingPanel', () => {
  beforeEach(() => {
    mocks.getSubscription.mockResolvedValue(subscription);
    mocks.getEntitlements.mockResolvedValue(entitlements);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('renders backend subscription state and measured entitlement usage', async () => {
    const user = userEvent.setup();
    render(<SubscriptionBillingPanel workspace={workspace} />);

    expect(await screen.findByText('Professional · Trial')).toBeInTheDocument();
    expect(screen.getByText('Professional subscription')).toBeInTheDocument();
    expect(screen.getByText(/Trial ends/)).toBeInTheDocument();
    expect(screen.getByText('Provider: Not connected')).toBeInTheDocument();
    expect(screen.getByText('Conversations this month')).toBeInTheDocument();
    expect(screen.getByText('1,200 / 3,000')).toBeInTheDocument();
    expect(screen.getByText('4 / 5')).toBeInTheDocument();
    expect(screen.getByText('8 / 10 (1 pending)')).toBeInTheDocument();
    expect(screen.getByText('450,000 / 2,000,000')).toBeInTheDocument();
    expect(screen.getByText('1.0 GB / 5.0 GB')).toBeInTheDocument();
    expect(screen.getByText(/CRM: Included/)).toBeInTheDocument();
    expect(screen.getByText(/White-label: Upgrade required/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Manage billing' }));
    expect(mocks.pushToast).toHaveBeenCalledWith(
      'Billing portal will open after a payment provider is connected',
      'info',
    );
    expect(mocks.getSubscription).toHaveBeenCalledWith('starter');
    expect(mocks.getEntitlements).toHaveBeenCalledWith('starter');
  });

  it('shows authorization failures instead of inventing billing access', async () => {
    mocks.getEntitlements.mockRejectedValueOnce(new Error('Insufficient permission'));
    render(<SubscriptionBillingPanel workspace={workspace} />);

    expect(await screen.findByText('Billing access is unavailable')).toBeInTheDocument();
    expect(screen.getByText('Insufficient permission')).toBeInTheDocument();
    await waitFor(() => expect(mocks.pushToast).toHaveBeenCalledWith('Insufficient permission', 'error'));
  });
});
