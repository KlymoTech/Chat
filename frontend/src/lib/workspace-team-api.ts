import { AUTH_SESSION_EVENT } from '@/lib/api';
import { readStorage, writeStorage } from '@/lib/storage';
import { activeWorkspaceId, persistActiveWorkspace } from '@/lib/workspace-api';
import type { Session } from '@/types';

export type WorkspaceRole = 'workspace_admin' | 'manager' | 'operator' | 'analyst' | 'viewer';
export type WorkspaceInvitationStatus = 'pending' | 'accepted' | 'declined' | 'revoked' | 'expired';

export interface WorkspaceMember {
  userId: string;
  name: string;
  email: string;
  role: WorkspaceRole;
  allAgentsAccess: boolean;
  agentIds: string[];
  joinedAt: string;
  isSelf: boolean;
}

export interface WorkspaceInvitation {
  id: string;
  email: string;
  role: WorkspaceRole;
  allAgentsAccess: boolean;
  agentIds: string[];
  status: WorkspaceInvitationStatus;
  expiresAt: string;
  lastSentAt: string | null;
  deliveryAttempts: number;
  deliveryState: 'not-sent' | 'sent' | 'failed';
  createdAt: string;
}

export interface WorkspaceAccessInput {
  role: WorkspaceRole;
  allAgentsAccess: boolean;
  agentIds: string[];
}

export interface WorkspaceInvitationCreate extends WorkspaceAccessInput {
  email: string;
}

export interface WorkspaceInvitationPreview {
  invitationId: string;
  email: string;
  tenantId: string;
  tenantName: string;
  tenantSlug: string;
  workspaceId: string;
  workspaceName: string;
  role: WorkspaceRole;
  allAgentsAccess: boolean;
  agentCount: number;
  expiresAt: string;
  existingUser: boolean;
}

export interface WorkspaceInvitationSession extends Session {
  tenantId: string;
  tenantSlug: string;
  workspaceId: string;
}

export interface WorkspaceInvitationSignupInput {
  token: string;
  name: string;
  password: string;
  termsAccepted: true;
  privacyAccepted: true;
}

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

export class WorkspaceTeamRequestError extends Error {
  constructor(message: string, readonly status: number, readonly detail?: unknown) {
    super(message);
    this.name = 'WorkspaceTeamRequestError';
  }
}

function bearer(): string | undefined {
  return readStorage<{ accessToken?: string } | null>(SESSION_KEY, null)?.accessToken;
}

async function request<T>(
  path: string,
  options: {
    method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
    body?: unknown;
    authenticated?: boolean;
    workspaceScoped?: boolean;
  } = {},
): Promise<T> {
  const {
    method = 'GET',
    body,
    authenticated = true,
    workspaceScoped = authenticated,
  } = options;
  const token = bearer();
  const workspaceId = activeWorkspaceId();
  const response = await fetch(`${API_URL}${path}`, {
    method,
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...(authenticated && token ? { Authorization: `Bearer ${token}` } : {}),
      ...(workspaceScoped && workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as {
      detail?: unknown;
      error?: { message?: string };
    } | null;
    const detail = payload?.detail;
    const message = payload?.error?.message
      ?? (typeof detail === 'string' ? detail : undefined)
      ?? `Workspace team request failed (${response.status})`;
    throw new WorkspaceTeamRequestError(message, response.status, payload);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const workspaceTeamApi = {
  listMembers: () => request<WorkspaceMember[]>('/workspace/members'),
  listInvitations: () => request<WorkspaceInvitation[]>('/workspace/invitations'),
  invite: (input: WorkspaceInvitationCreate) => request<WorkspaceInvitation>('/workspace/invitations', {
    method: 'POST',
    body: input,
  }),
  updateMember: (userId: string, input: WorkspaceAccessInput) => request<WorkspaceMember>(
    `/workspace/members/${encodeURIComponent(userId)}`,
    { method: 'PATCH', body: input },
  ),
  removeMember: (userId: string) => request<void>(
    `/workspace/members/${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  ),
  resendInvitation: (invitationId: string) => request<WorkspaceInvitation>(
    `/workspace/invitations/${encodeURIComponent(invitationId)}/resend`,
    { method: 'POST' },
  ),
  revokeInvitation: (invitationId: string) => request<void>(
    `/workspace/invitations/${encodeURIComponent(invitationId)}`,
    { method: 'DELETE' },
  ),
};

export const workspaceInvitationApi = {
  preview: (token: string) => request<WorkspaceInvitationPreview>('/workspace-invitations/preview', {
    method: 'POST',
    body: { token },
    authenticated: false,
    workspaceScoped: false,
  }),
  decline: (token: string) => request<{ declined: true }>('/workspace-invitations/decline', {
    method: 'POST',
    body: { token },
    authenticated: false,
    workspaceScoped: false,
  }),
  accept: (token: string) => request<WorkspaceInvitationSession>('/workspace-invitations/accept', {
    method: 'POST',
    body: { token },
    authenticated: true,
    workspaceScoped: false,
  }),
  signup: (input: WorkspaceInvitationSignupInput) => request<WorkspaceInvitationSession>(
    '/workspace-invitations/signup',
    {
      method: 'POST',
      body: input,
      authenticated: false,
      workspaceScoped: false,
    },
  ),
};

export function activateWorkspaceInvitationSession(value: WorkspaceInvitationSession): void {
  const safeSession: Session = {
    accessToken: value.accessToken,
    expiresAt: value.expiresAt,
    user: value.user,
  };
  writeStorage(SESSION_KEY, safeSession);
  persistActiveWorkspace(value.workspaceId);
  window.dispatchEvent(new Event(AUTH_SESSION_EVENT));
}
