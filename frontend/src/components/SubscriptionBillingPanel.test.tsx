import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SubscriptionBillingPanel } from '@/components/SubscriptionBillingPanel';
import type { WorkspaceSettings } from '@/lib/workspace-api';

const mocks = vi.hoisted(() => ({
  pushToast: vi.fn(),
  getSubscription: vi.fn(),
}));

vi.mock('@/components/providers', () => ({
  useToast: () => ({ pushToast: mocks.pushToast }),
}));

vi.mock('@/lib/billing-api', () => ({
  billingApi: { getSubscription: mocks.getSubscription },
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

describe('SubscriptionBillingPanel', () => {
  beforeEach(() => {
    mocks.getSubscription.mockResolvedValue(subscription);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('renders backend subscription state without removing existing billing actions and usage', async () => {
    const user = userEvent.setup();
    render(<SubscriptionBillingPanel workspace={workspace} />);

    expect(await screen.findByText('Professional · Trial')).toBeInTheDocument();
    expect(screen.getByText('Professional subscription')).toBeInTheDocument();
    expect(screen.getByText(/Trial ends/)).toBeInTheDocument();
    expect(screen.getByText('Provider: Not connected')).toBeInTheDocument();
    expect(screen.getByText('Conversations')).toBeInTheDocument();
    expect(screen.getByText('AI agents')).toBeInTheDocument();
    expect(screen.getByText('Team members')).toBeInTheDocument();
    expect(screen.getByText('4 / 20')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Manage billing' }));
    expect(mocks.pushToast).toHaveBeenCalledWith(
      'Billing portal will open after a payment provider is connected',
      'info',
    );
    expect(mocks.getSubscription).toHaveBeenCalledWith('starter');
  });

  it('shows authorization failures instead of inventing a subscription', async () => {
    mocks.getSubscription.mockRejectedValueOnce(new Error('Insufficient permission'));
    render(<SubscriptionBillingPanel workspace={workspace} />);

    expect(await screen.findByText('Billing access is unavailable')).toBeInTheDocument();
    expect(screen.getByText('Insufficient permission')).toBeInTheDocument();
    await waitFor(() => expect(mocks.pushToast).toHaveBeenCalledWith('Insufficient permission', 'error'));
  });
});
