import { activeWorkspaceId } from '@/lib/workspace-api';
import { readStorage } from '@/lib/storage';
import type { Session } from '@/types';

export interface PlatformAdminAccess {
  authorized: boolean;
  email: string;
}

export interface PlatformOperations {
  status: 'healthy' | 'degraded' | string;
  failedIngestionJobs: number;
  unpublishedOutboxEvents: number;
  oldestUnpublishedEventAt: string | null;
  quarantinedEvents: number;
  channelIssues: number;
  crmConnectionIssues: number;
  crmDeliveryIssues: number;
  openCrmDeadLetters: number;
  criticalAuditEvents24h: number;
}

export interface PlatformOverview {
  tenants: number;
  workspaces: number;
  users: number;
  agents: number;
  conversations: number;
  leads: number;
  subscriptions: {
    trial: number;
    active: number;
    pastDue: number;
    suspended: number;
    cancelled: number;
  };
  operations: PlatformOperations;
}

export interface PlatformTenantSummary {
  id: string;
  name: string;
  slug: string;
  plan: string;
  subscriptionStatus: string;
  workspaceCount: number;
  memberCount: number;
  agentCount: number;
  conversationCount: number;
  leadCount: number;
  channelIssues: number;
  crmIssues: number;
  createdAt: string;
}

export interface PlatformWorkspaceSummary {
  id: string;
  name: string;
  slug: string;
  status: string;
  memberCount: number;
  agentCount: number;
  conversationCount: number;
  leadCount: number;
  createdAt: string;
}

export interface PlatformAuditSummary {
  id: string;
  action: string;
  entityType: string;
  entityId: string;
  category: string;
  severity: string;
  outcome: string;
  workspaceId: string | null;
  createdAt: string;
}

export interface PlatformTenantDetail extends PlatformTenantSummary {
  provider: string | null;
  currentPeriodEnd: string | null;
  cancelAtPeriodEnd: boolean;
  workspaces: PlatformWorkspaceSummary[];
  recentAudit: PlatformAuditSummary[];
}

export interface PlatformTenantList {
  items: PlatformTenantSummary[];
  total: number;
  limit: number;
  offset: number;
}

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

class PlatformAdminRequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = 'PlatformAdminRequestError';
  }
}

function headers(): Record<string, string> {
  const session = readStorage<Session | null>(SESSION_KEY, null);
  const workspaceId = activeWorkspaceId();
  return {
    Accept: 'application/json',
    ...(session ? { Authorization: `Bearer ${session.accessToken}` } : {}),
    ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
  };
}

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    credentials: 'include',
    headers: headers(),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { error?: { message?: string } } | null;
    throw new PlatformAdminRequestError(
      payload?.error?.message ?? `Platform admin request failed (${response.status})`,
      response.status,
    );
  }
  return response.json() as Promise<T>;
}

export const platformAdminApi = {
  async canAccess(): Promise<boolean> {
    try {
      const value = await request<PlatformAdminAccess>('/platform-admin/access');
      return value.authorized;
    } catch (error) {
      if (error instanceof PlatformAdminRequestError && [401, 403].includes(error.status)) return false;
      throw error;
    }
  },

  access(): Promise<PlatformAdminAccess> {
    return request<PlatformAdminAccess>('/platform-admin/access');
  },

  overview(): Promise<PlatformOverview> {
    return request<PlatformOverview>('/platform-admin/overview');
  },

  tenants(search = '', limit = 50, offset = 0): Promise<PlatformTenantList> {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (search.trim()) params.set('search', search.trim());
    return request<PlatformTenantList>(`/platform-admin/tenants?${params.toString()}`);
  },

  tenant(tenantId: string): Promise<PlatformTenantDetail> {
    return request<PlatformTenantDetail>(`/platform-admin/tenants/${encodeURIComponent(tenantId)}`);
  },
};
