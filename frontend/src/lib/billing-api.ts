import { activeWorkspaceId } from '@/lib/workspace-api';
import { readStorage } from '@/lib/storage';

export type SubscriptionStatus = 'trial' | 'active' | 'past_due' | 'suspended' | 'cancelled';

export interface TenantSubscription {
  id: string;
  tenantId: string;
  plan: string;
  status: SubscriptionStatus;
  provider: string | null;
  trialEndsAt: string | null;
  currentPeriodStart: string | null;
  currentPeriodEnd: string | null;
  cancelAtPeriodEnd: boolean;
  pastDueAt: string | null;
  suspendedAt: string | null;
  cancelledAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface EntitlementLimits {
  workspaces: number | null;
  agents: number | null;
  members: number | null;
  conversationsMonthly: number | null;
  tokensMonthly: number | null;
  storageBytes: number | null;
}

export interface EntitlementUsage {
  workspaces: number;
  agents: number;
  members: number;
  pendingMemberSeats: number;
  conversationsMonthly: number;
  tokensMonthly: number;
  storageBytes: number;
}

export interface TenantEntitlements {
  plan: string;
  subscriptionStatus: SubscriptionStatus;
  limits: EntitlementLimits;
  usage: EntitlementUsage;
  features: {
    allowedChannels: string[];
    crm: boolean;
    api: boolean;
    whiteLabel: boolean;
  };
}

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

class BillingRequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = 'BillingRequestError';
  }
}

function bearer(): string | undefined {
  return readStorage<{ accessToken?: string } | null>(SESSION_KEY, null)?.accessToken;
}

function demoSubscription(plan: string): TenantSubscription {
  const now = new Date().toISOString();
  return {
    id: 'subscription-demo',
    tenantId: 'tenant-demo',
    plan: plan || 'starter',
    status: 'active',
    provider: null,
    trialEndsAt: null,
    currentPeriodStart: null,
    currentPeriodEnd: null,
    cancelAtPeriodEnd: false,
    pastDueAt: null,
    suspendedAt: null,
    cancelledAt: null,
    createdAt: now,
    updatedAt: now,
  };
}

function demoEntitlements(plan: string): TenantEntitlements {
  const normalized = plan || 'starter';
  const known = normalized === 'business'
    ? { workspaces: 10, agents: 10, members: 20, conversationsMonthly: 5000, tokensMonthly: 5_000_000, storageBytes: 20 * 1024 ** 3 }
    : normalized === 'professional'
      ? { workspaces: 3, agents: 5, members: 10, conversationsMonthly: 3000, tokensMonthly: 2_000_000, storageBytes: 5 * 1024 ** 3 }
      : normalized === 'enterprise'
        ? { workspaces: null, agents: null, members: null, conversationsMonthly: null, tokensMonthly: null, storageBytes: null }
        : { workspaces: 1, agents: 2, members: 3, conversationsMonthly: 1000, tokensMonthly: 500_000, storageBytes: 1024 ** 3 };
  return {
    plan: normalized,
    subscriptionStatus: 'active',
    limits: known,
    usage: {
      workspaces: 1,
      agents: 0,
      members: 1,
      pendingMemberSeats: 0,
      conversationsMonthly: 0,
      tokensMonthly: 0,
      storageBytes: 0,
    },
    features: {
      allowedChannels: ['website', 'widget', 'api'],
      crm: normalized !== 'starter',
      api: true,
      whiteLabel: normalized === 'business' || normalized === 'enterprise',
    },
  };
}

async function remote<T>(path: string): Promise<T> {
  const token = bearer();
  const workspaceId = activeWorkspaceId();
  const response = await fetch(`${API_URL}${path}`, {
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { error?: { message?: string } } | null;
    throw new BillingRequestError(
      payload?.error?.message ?? `Billing request failed (${response.status})`,
      response.status,
    );
  }
  return response.json() as Promise<T>;
}

function shouldSurface(error: unknown): boolean {
  return error instanceof BillingRequestError && error.status >= 400 && error.status < 500;
}

export const billingApi = {
  async getSubscription(fallbackPlan = 'starter'): Promise<TenantSubscription> {
    try {
      return await remote<TenantSubscription>('/billing/subscription');
    } catch (error) {
      if (shouldSurface(error)) throw error;
      return demoSubscription(fallbackPlan);
    }
  },
  async getEntitlements(fallbackPlan = 'starter'): Promise<TenantEntitlements> {
    try {
      return await remote<TenantEntitlements>('/billing/entitlements');
    } catch (error) {
      if (shouldSurface(error)) throw error;
      return demoEntitlements(fallbackPlan);
    }
  },
};
