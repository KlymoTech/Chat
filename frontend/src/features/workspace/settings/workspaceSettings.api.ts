import { activeWorkspaceId, workspacePresentationKey, WorkspaceRequestError } from '@/lib/workspace-api';
import { readStorage } from '@/lib/storage';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

export type SettingsSection = 'general' | 'members' | 'roles' | 'teams' | 'security' | 'notifications' | 'channels' | 'integrations' | 'developer' | 'audit' | 'billing' | 'branding';
export type BusinessHours = { enabled: boolean; timezone: string; schedule: Record<string, string[]> };
export type WorkspaceGeneralMetadata = { workspaceId: string; tenantId: string; organization: string; status: string; owner: { id: string; name: string; email: string } | null };
export type GeneralSettings = { industry: string; country: string; timeFormat: '12h' | '24h'; currency: string; weekStart: 'monday' | 'sunday'; description: string; workspaceIcon: string; businessHours: BusinessHours };
export type SecuritySettings = { sensitiveDataMasking: boolean; securityContact: string | null; mfaEnforcement: 'optional' | 'admins' | 'all'; sessionTimeoutMinutes: number; passwordMinLength: number; ipAllowlist: string[]; ipDenylist: string[]; trustedDomains: string[]; webhookSigningRequired: boolean; securityNotifications: boolean };
export type NotificationSettings = { memberChanges: boolean; securityAlerts: boolean; billingAlerts: boolean; channelFailures: boolean; integrationFailures: boolean; weeklyDigest: boolean; recipients: string[] };
export type DeveloperSettings = { sandboxMode: boolean; webhookSigningEnabled: boolean; webhookEvents: string[]; rateLimitPerMinute: number; requestLogRetentionDays: number; webhookRetryLimit: number };
export type CustomRole = { id: string; name: string; description: string; permissions: string[]; resources: { selected: Record<string, string[]>; conversationScope: 'all' | 'assigned' | 'team' } };
export type RolesSettings = { customRoles: CustomRole[]; memberRoleIds: Record<string, string[]> };
export type WorkspaceTeam = { id: string; name: string; description: string; memberIds: string[]; managerIds: string[]; roleIds: string[]; queueIds: string[]; agentIds: string[]; channelIds: string[]; businessHours: BusinessHours; escalationRule: string };
export type TeamsSettings = { teams: WorkspaceTeam[] };
export type DashboardWidget = { id: string; type: string; x: number; y: number; width: number; height: number; visible: boolean; audience: string[]; config: Record<string, unknown> };
export type DashboardSettings = { layoutVersion: number; landingScreen: string; widgets: DashboardWidget[] };
export type LegacyBrandIdentity = { companyName: string; logoDataUrl: string; faviconDataUrl: string; appIconDataUrl: string; primaryColor: string; secondaryColor: string; supportEmail: string | null; supportUrl: string; browserTitle: string; brandedLogin: boolean; brandedDashboard: boolean; brandedWidget: boolean; brandedEmails: boolean; removePlatformBranding: boolean };
export type ExtendedBranding = { identity: LegacyBrandIdentity; colors: Record<string, string>; typography: Record<string, string | number>; dashboard: DashboardSettings; authentication: { loginLogo: string; loginBackground: string; loginTitle: string; loginDescription: string; termsUrl: string; privacyUrl: string; supportUrl: string; footer: string }; email: { logo: string; senderName: string; replyTo: string | null; footer: string; enabledTemplates: string[] }; widget: { launcherIcon: string; launcherColor: string; position: 'bottom-left' | 'bottom-right'; greeting: string; widgetLogo: string; header: string; background: string; userMessageColor: string; agentMessageColor: string; font: 'Inter' | 'DM Sans' | 'Manrope' | 'System UI'; privacyUrl: string; poweredByLabel: string; offlineMessage: string }; navigation: Record<string, unknown> };
export type BrandVersion = { version: number; createdBy: string; publishedAt: string; changeNote: string; branding: ExtendedBranding };
export type DomainRecord = { id: string; hostname: string; status: 'pending' | 'dns_pending' | 'verifying' | 'verified' | 'certificate_pending' | 'active' | 'failed' | 'disabled'; verificationName: string; verificationValue: string; failureReason: string; createdAt: string };
export type WorkspaceSettingsBundle = { general: GeneralSettings; security: SecuritySettings; notifications: NotificationSettings; developer: DeveloperSettings; roles: RolesSettings; teams: TeamsSettings; dashboard: DashboardSettings; brandingDraft: ExtendedBranding; brandingPublished: ExtendedBranding | null; brandingVersions: BrandVersion[]; domains: { domains: DomainRecord[] } };
export type CapabilityCatalog = { permissions: string[]; builtinRoles: Record<string, string[]>; resourceKinds: string[] };

function storedToken(): string | undefined { return readStorage<{ accessToken?: string } | null>(SESSION_KEY, null)?.accessToken; }

async function request<T>(path: string, method: 'GET' | 'POST' | 'PATCH' = 'GET', body?: unknown): Promise<T> {
  const identity = workspacePresentationKey();
  const workspaceId = activeWorkspaceId();
  const token = storedToken();
  const response = await fetch(`${API_URL}${path}`, {
    method, cache: 'no-store', credentials: 'include',
    headers: { Accept: 'application/json', ...(body === undefined ? {} : { 'Content-Type': 'application/json' }), ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload: unknown = await response.json().catch(() => undefined);
  if (identity !== workspacePresentationKey() || workspaceId !== activeWorkspaceId()) throw new DOMException('Workspace context changed', 'AbortError');
  if (!response.ok) {
    const value = payload as { error?: { message?: string }; detail?: unknown } | undefined;
    throw new WorkspaceRequestError(value?.error?.message ?? (typeof value?.detail === 'string' ? value.detail : `Workspace settings request failed (${response.status})`), response.status);
  }
  return payload as T;
}

export const workspaceSettingsApi = {
  get: () => request<WorkspaceSettingsBundle>('/workspace/settings'),
  generalMetadata: () => request<WorkspaceGeneralMetadata>('/workspace/settings/general/metadata'),
  capabilities: () => request<CapabilityCatalog>('/workspace/settings/capabilities'),
  saveGeneral: (value: GeneralSettings) => request<GeneralSettings>('/workspace/settings/general', 'PATCH', value),
  saveSecurity: (value: SecuritySettings) => request<SecuritySettings>('/workspace/settings/security', 'PATCH', value),
  saveNotifications: (value: NotificationSettings) => request<NotificationSettings>('/workspace/settings/notifications', 'PATCH', value),
  saveDeveloper: (value: DeveloperSettings) => request<DeveloperSettings>('/workspace/settings/developer', 'PATCH', value),
  saveRoles: (value: RolesSettings) => request<RolesSettings>('/workspace/settings/roles', 'PATCH', value),
  saveTeams: (value: TeamsSettings) => request<TeamsSettings>('/workspace/settings/teams', 'PATCH', value),
  saveDashboard: (value: DashboardSettings) => request<DashboardSettings>('/workspace/settings/dashboard', 'PATCH', value),
  saveBrandDraft: (value: ExtendedBranding) => request<ExtendedBranding>('/workspace/settings/branding/draft', 'PATCH', value),
  publishBrand: (changeNote: string) => request<BrandVersion>('/workspace/settings/branding/publish', 'POST', { changeNote }),
  rollbackBrand: (version: number, changeNote = 'Rollback') => request<BrandVersion>('/workspace/settings/branding/rollback', 'POST', { version, changeNote }),
  createDomain: (hostname: string) => request<DomainRecord>('/workspace/settings/domains', 'POST', { hostname }),
  verifyDomain: (id: string) => request<DomainRecord>(`/workspace/settings/domains/${id}/verification-start`, 'POST'),
  disableDomain: (id: string) => request<DomainRecord>(`/workspace/settings/domains/${id}/disable`, 'POST'),
};
