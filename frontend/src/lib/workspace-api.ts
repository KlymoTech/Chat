import { readStorage, writeStorage } from '@/lib/storage';

export type DnsStatus = 'not-configured' | 'pending' | 'verified';
export type WorkspaceRole = 'workspace_admin' | 'manager' | 'operator' | 'analyst' | 'viewer';

export interface WorkspacePreferences {
  timezone: string;
  defaultLanguage: string;
  dateFormat: 'DD/MM/YYYY' | 'MM/DD/YYYY' | 'YYYY-MM-DD';
}

export interface WhiteLabelSettings {
  companyName: string;
  logoDataUrl: string;
  faviconDataUrl: string;
  appIconDataUrl: string;
  primaryColor: string;
  secondaryColor: string;
  supportEmail: string | null;
  supportUrl: string;
  browserTitle: string;
  customDomain: string;
  dnsStatus: DnsStatus;
  brandedLogin: boolean;
  brandedDashboard: boolean;
  brandedWidget: boolean;
  brandedEmails: boolean;
  removePlatformBranding: boolean;
}

export interface WorkspaceSettings {
  id: string;
  tenantId?: string;
  tenantName?: string;
  name: string;
  slug: string;
  status?: 'active' | 'archived';
  role?: WorkspaceRole;
  permissions?: string[];
  plan: string;
  memberCount: number;
  preferences: WorkspacePreferences;
  whiteLabel: WhiteLabelSettings;
  educationCreateUpsellLeads?: boolean;
}

export interface WorkspaceTeamMember {
  id: string;
  name: string;
  email: string;
  role: WorkspaceRole;
  tenantRole: 'owner' | 'admin' | 'billing_admin' | 'security_admin' | 'member' | 'analyst';
  status: 'active';
}

export interface WorkspaceTeamInvitation {
  id: string;
  email: string;
  role: WorkspaceRole;
  status: 'invited';
  expiresAt: string;
  createdAt: string;
}

export interface WorkspaceTeam {
  members: WorkspaceTeamMember[];
  invitations: WorkspaceTeamInvitation[];
}

export type WorkspacePatch = Partial<Pick<WorkspaceSettings, 'name' | 'slug' | 'preferences' | 'whiteLabel' | 'educationCreateUpsellLeads'>>;
export interface WorkspaceCreate {
  name: string;
  slug: string;
  timezone?: string;
  defaultLanguage?: string;
  dateFormat?: WorkspacePreferences['dateFormat'];
}

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const STORAGE_KEY = 'northstar.workspace';
const ACTIVE_WORKSPACE_KEY = 'northstar.active-workspace-id';
const SESSION_KEY = 'northstar.session';
const LEGACY_MEMBERS_KEY = 'northstar.workspace.members';
export const WORKSPACE_CHANGED_EVENT = 'northstar:active-workspace-changed';

class WorkspaceRequestError extends Error {
  constructor(message: string, readonly status: number) { super(message); this.name = 'WorkspaceRequestError'; }
}

const defaults: WorkspaceSettings = {
  id: 'workspace-demo',
  name: 'Northstar Workspace',
  slug: 'northstar',
  plan: 'business',
  memberCount: 1,
  educationCreateUpsellLeads: false,
  preferences: { timezone: 'Asia/Calcutta', defaultLanguage: 'English', dateFormat: 'DD/MM/YYYY' },
  whiteLabel: {
    companyName: 'Northstar AI', logoDataUrl: '', faviconDataUrl: '', appIconDataUrl: '',
    primaryColor: '#0c0b0b', secondaryColor: '#6b6b70', supportEmail: 'support@northstar.ai',
    supportUrl: 'https://northstar.ai/support', browserTitle: 'Northstar AI', customDomain: '',
    dnsStatus: 'not-configured', brandedLogin: true, brandedDashboard: true, brandedWidget: true,
    brandedEmails: true, removePlatformBranding: false,
  },
};

function localWorkspace(): WorkspaceSettings {
  const saved = readStorage<Partial<WorkspaceSettings>>(STORAGE_KEY, {});
  return {
    ...defaults,
    ...saved,
    preferences: { ...defaults.preferences, ...saved.preferences },
    whiteLabel: { ...defaults.whiteLabel, ...saved.whiteLabel },
  };
}

function bearer(): string | undefined {
  return readStorage<{ accessToken?: string } | null>(SESSION_KEY, null)?.accessToken;
}

export function activeWorkspaceId(): string | null {
  return readStorage<string | null>(ACTIVE_WORKSPACE_KEY, null);
}

export function persistActiveWorkspace(workspaceId: string): void {
  writeStorage(ACTIVE_WORKSPACE_KEY, workspaceId);
  window.dispatchEvent(new CustomEvent(WORKSPACE_CHANGED_EVENT, { detail: workspaceId }));
}

async function remote<T>(path: string, method: 'GET' | 'POST' | 'PATCH', body?: unknown, includeWorkspace = true): Promise<T> {
  const token = bearer();
  const workspaceId = activeWorkspaceId();
  const response = await fetch(`${API_URL}${path}`, {
    method,
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...(body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(includeWorkspace && workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { error?: { message?: string }; detail?: string } | null;
    throw new WorkspaceRequestError(
      payload?.error?.message ?? payload?.detail ?? `Workspace request failed (${response.status})`,
      response.status,
    );
  }
  return response.json() as Promise<T>;
}

function legacyTeam(): WorkspaceTeam {
  const legacy = readStorage<Array<{ id: string; name: string; email: string; role: string; status: string }>>(
    LEGACY_MEMBERS_KEY,
    [],
  );
  return {
    members: [],
    invitations: legacy.map((member) => ({
      id: member.id,
      email: member.email,
      role: member.role === 'Admin' ? 'workspace_admin' : member.role === 'Analyst' ? 'analyst' : 'operator',
      status: 'invited' as const,
      createdAt: new Date().toISOString(),
      expiresAt: new Date(Date.now() + 7 * 86_400_000).toISOString(),
    })),
  };
}

export const workspaceApi = {
  async get(): Promise<WorkspaceSettings> {
    try {
      const value = await remote<WorkspaceSettings>('/workspace', 'GET');
      writeStorage(STORAGE_KEY, value);
      return value;
    } catch {
      return localWorkspace();
    }
  },
  async update(patch: WorkspacePatch): Promise<WorkspaceSettings> {
    const current = localWorkspace();
    const optimistic: WorkspaceSettings = {
      ...current,
      ...patch,
      preferences: { ...current.preferences, ...patch.preferences },
      whiteLabel: { ...current.whiteLabel, ...patch.whiteLabel },
    };
    writeStorage(STORAGE_KEY, optimistic);
    try {
      const value = await remote<WorkspaceSettings>('/workspace', 'PATCH', patch);
      writeStorage(STORAGE_KEY, value);
      window.dispatchEvent(new CustomEvent('northstar:workspace-changed', { detail: value }));
      return value;
    } catch (error) {
      if (error instanceof WorkspaceRequestError && error.status >= 400 && error.status < 500) throw error;
      window.dispatchEvent(new CustomEvent('northstar:workspace-changed', { detail: optimistic }));
      return optimistic;
    }
  },
  async list(): Promise<WorkspaceSettings[]> {
    try {
      const values = await remote<WorkspaceSettings[]>('/workspaces', 'GET', undefined, false);
      if (values.length > 0) return values;
    } catch {
      // Keep demo/offline mode usable with its locally persisted workspace.
    }
    return [localWorkspace()];
  },
  async create(input: WorkspaceCreate): Promise<WorkspaceSettings> {
    const value = await remote<WorkspaceSettings>('/workspaces', 'POST', input, false);
    persistActiveWorkspace(value.id);
    writeStorage(STORAGE_KEY, value);
    return value;
  },
  async getTeam(): Promise<WorkspaceTeam> {
    try {
      return await remote<WorkspaceTeam>('/workspace/team', 'GET');
    } catch (error) {
      if (error instanceof WorkspaceRequestError && error.status >= 400 && error.status < 500) throw error;
      return legacyTeam();
    }
  },
  async inviteMember(email: string, role: WorkspaceRole): Promise<WorkspaceTeam> {
    try {
      const value = await remote<WorkspaceTeam>('/workspace/invitations', 'POST', { email, role });
      writeStorage(LEGACY_MEMBERS_KEY, []);
      return value;
    } catch (error) {
      if (error instanceof WorkspaceRequestError && error.status >= 400 && error.status < 500) throw error;
      const current = legacyTeam();
      const invitation: WorkspaceTeamInvitation = {
        id: crypto.randomUUID(),
        email,
        role,
        status: 'invited',
        createdAt: new Date().toISOString(),
        expiresAt: new Date(Date.now() + 7 * 86_400_000).toISOString(),
      };
      const next = { ...current, invitations: [invitation, ...current.invitations] };
      writeStorage(LEGACY_MEMBERS_KEY, next.invitations.map((item) => ({
        id: item.id,
        name: item.email.split('@')[0] ?? item.email,
        email: item.email,
        role: item.role === 'workspace_admin' ? 'Admin' : item.role === 'analyst' ? 'Analyst' : 'Member',
        status: 'Invited',
      })));
      return next;
    }
  },
};

export const workspaceDefaults = defaults;
