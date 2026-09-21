import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Badge, Button, Card, PageLoader } from '@/components/ui';
import { useToast } from '@/components/providers';
import { SubscriptionBillingPanel } from '@/components/SubscriptionBillingPanel';
import { WorkspaceBrandingControlCenter } from '@/features/branding/WorkspaceBrandingControlCenter';
import { workspaceApi, type WorkspaceSettings } from '@/lib/workspace-api';
import { WorkspaceDeveloperSettings } from './WorkspaceDeveloperSettings';
import { WorkspaceGeneralSettings } from './WorkspaceGeneralSettings';
import { WorkspaceMembersSettings } from './WorkspaceMembersSettings';
import { WorkspaceNotificationsSettings } from './WorkspaceNotificationsSettings';
import { WorkspaceRolesSettings } from './WorkspaceRolesSettings';
import { WorkspaceSecuritySettings } from './WorkspaceSecuritySettings';
import { WorkspaceSettingsNavigation } from './WorkspaceSettingsNavigation';
import { WorkspaceTeamsSettings } from './WorkspaceTeamsSettings';
import {
  workspaceSettingsApi,
  type CapabilityCatalog,
  type SettingsSection,
  type WorkspaceSettingsBundle,
} from './workspaceSettings.api';
import '@/pages/WorkspaceTeam.css';

const sections: SettingsSection[] = [
  'general', 'members', 'roles', 'teams', 'security', 'notifications',
  'channels', 'integrations', 'developer', 'audit', 'billing', 'branding',
];

const emptyCapabilities: CapabilityCatalog = {
  permissions: [],
  builtinRoles: {},
  resourceKinds: [],
};

function requiredPermission(section: SettingsSection): string | null {
  return {
    general: 'settings.view',
    members: 'members.view',
    roles: 'roles.manage',
    teams: 'teams.manage',
    security: 'settings.view',
    notifications: 'settings.view',
    channels: 'channels.view',
    integrations: 'integrations.view',
    developer: 'settings.view',
    audit: 'audit.view',
    billing: 'billing.view',
    branding: 'branding.view',
  }[section];
}

export function WorkspaceSettingsPage() {
  const { section: rawSection } = useParams();
  const navigate = useNavigate();
  const { pushToast } = useToast();
  const section = sections.includes(rawSection as SettingsSection) ? rawSection as SettingsSection : 'general';
  const [workspace, setWorkspace] = useState<WorkspaceSettings | null>(null);
  const [bundle, setBundle] = useState<WorkspaceSettingsBundle | null>(null);
  const [capabilities, setCapabilities] = useState<CapabilityCatalog | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let current = true;
    workspaceApi.get()
      .then(async (workspaceValue) => {
        const [settingsValue, catalog] = await Promise.all([
          workspaceSettingsApi.get(),
          workspaceValue.permissions.includes('roles.manage')
            ? workspaceSettingsApi.capabilities()
            : Promise.resolve(emptyCapabilities),
        ]);
        if (!current) return;
        setWorkspace(workspaceValue);
        setBundle(settingsValue);
        setCapabilities(catalog);
        setError('');
      })
      .catch((reason: unknown) => {
        if (current) setError(reason instanceof Error ? reason.message : 'Workspace settings could not be loaded');
      });
    return () => { current = false; };
  }, []);

  const permissions = workspace?.permissions ?? [];
  const canManage = permissions.includes('settings.manage');
  async function save<T>(work: () => Promise<T>, apply: (value: T) => void, message: string) {
    setSaving(true);
    try {
      const value = await work();
      apply(value);
      pushToast(message);
    } catch (reason) {
      pushToast(reason instanceof Error ? reason.message : 'Settings could not be saved', 'error');
    } finally {
      setSaving(false);
    }
  }

  if (error) return <div className="page"><h2>Workspace settings could not be loaded</h2><p role="alert">{error}</p><Button onClick={() => window.location.reload()}>Retry</Button></div>;
  if (!workspace || !bundle || !capabilities) return <PageLoader />;

  const permission = requiredPermission(section);
  const sectionAllowed = permission === null || permissions.includes(permission);

  return <div className="page workspace-console-page">
    <div className="page-heading page-heading--split"><div><span className="page-kicker">Workspace administration</span><h2>Settings</h2><p>Workspace-owned configuration, access, security, developer controls, billing, and white label.</p></div><Badge tone="brand">{workspace.plan} plan</Badge></div>
    <div className="workspace-console-layout">
      <WorkspaceSettingsNavigation active={section} permissions={permissions} onSelect={(next) => navigate(`/workspace/settings/${next}`)} />
      <div className="workspace-console-content">
        {!sectionAllowed ? <Card className="workspace-panel"><div className="workspace-panel__body"><h3>Access unavailable</h3><p>Your current workspace permissions do not allow access to this settings section.</p></div></Card> : null}
        {sectionAllowed && section === 'general' ? <WorkspaceGeneralSettings workspace={workspace} bundle={bundle} disabled={!canManage || saving} onWorkspace={setWorkspace} onBundle={setBundle} onSave={() => void save(
          async () => {
            const updated = await workspaceApi.update({ name: workspace.name, slug: workspace.slug, preferences: workspace.preferences });
            await workspaceSettingsApi.saveGeneral(bundle.general);
            return updated;
          }, setWorkspace, 'Workspace general settings saved')} /> : null}
        {sectionAllowed && section === 'members' ? <WorkspaceMembersSettings workspace={workspace} /> : null}
        {sectionAllowed && section === 'roles' ? <WorkspaceRolesSettings value={bundle.roles} catalog={capabilities} disabled={saving || !permissions.includes('roles.manage')} onChange={(roles) => setBundle({ ...bundle, roles })} onSave={() => void save(() => workspaceSettingsApi.saveRoles(bundle.roles), (roles) => setBundle({ ...bundle, roles }), 'Roles saved')} /> : null}
        {sectionAllowed && section === 'teams' ? <WorkspaceTeamsSettings value={bundle.teams} roles={bundle.roles} disabled={saving || !permissions.includes('teams.manage')} onChange={(teams) => setBundle({ ...bundle, teams })} onSave={() => void save(() => workspaceSettingsApi.saveTeams(bundle.teams), (teams) => setBundle({ ...bundle, teams }), 'Teams saved')} /> : null}
        {sectionAllowed && section === 'security' ? <WorkspaceSecuritySettings bundle={bundle} disabled={!canManage || saving} onBundle={setBundle} onSave={() => void save(() => workspaceSettingsApi.saveSecurity(bundle.security), (security) => setBundle({ ...bundle, security }), 'Security policy saved')} /> : null}
        {sectionAllowed && section === 'notifications' ? <WorkspaceNotificationsSettings bundle={bundle} disabled={!canManage || saving} onBundle={setBundle} onSave={() => void save(() => workspaceSettingsApi.saveNotifications(bundle.notifications), (notifications) => setBundle({ ...bundle, notifications }), 'Notification settings saved')} /> : null}
        {sectionAllowed && section === 'channels' ? <LinkSection title="Workspace channels" description="Channel connections remain owned by the existing channel pipeline. Manage them without duplicating connection logic." href="/integrations" action="Open channels and integrations" /> : null}
        {sectionAllowed && section === 'integrations' ? <LinkSection title="Workspace integrations" description="CRM, WhatsApp, and other integrations keep using the existing integration services and workspace scoping." href="/integrations" action="Open integrations" /> : null}
        {sectionAllowed && section === 'developer' ? <WorkspaceDeveloperSettings workspace={workspace} bundle={bundle} disabled={!canManage || saving} onBundle={setBundle} onSave={() => void save(() => workspaceSettingsApi.saveDeveloper(bundle.developer), (developer) => setBundle({ ...bundle, developer }), 'Developer policy saved')} /> : null}
        {sectionAllowed && section === 'audit' ? <LinkSection title="Workspace audit" description="Administrative writes from this settings center are recorded in the existing audit pipeline." href="/audit" action="Open audit log" /> : null}
        {sectionAllowed && section === 'billing' ? <SubscriptionBillingPanel workspace={workspace} /> : null}
        {sectionAllowed && section === 'branding' ? <WorkspaceBrandingControlCenter bundle={bundle} permissions={permissions} onChange={setBundle} /> : null}
      </div>
    </div>
  </div>;
}

function LinkSection({ title, description, href, action }: { title: string; description: string; href: string; action: string }) {
  return <Card className="workspace-panel"><div className="workspace-panel__body"><h3>{title}</h3><p>{description}</p><a className="button button--primary button--md" href={href}>{action}</a></div></Card>;
}
