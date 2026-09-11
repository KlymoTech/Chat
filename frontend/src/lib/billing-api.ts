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

async function remote(): Promise<TenantSubscription> {
  const token = bearer();
  const workspaceId = activeWorkspaceId();
  const response = await fetch(`${API_URL}/billing/subscription`, {
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
  return response.json() as Promise<TenantSubscription>;
}

export const billingApi = {
  async getSubscription(fallbackPlan = 'starter'): Promise<TenantSubscription> {
    try {
      return await remote();
    } catch (error) {
      if (error instanceof BillingRequestError && error.status >= 400 && error.status < 500) throw error;
      return demoSubscription(fallbackPlan);
    }
  },
};
