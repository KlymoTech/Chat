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
    Promise.all([workspaceApi.get(), workspaceSettingsApi.get(), workspaceSettingsApi.capabilities()])
      .then(([workspaceValue, settingsValue, catalog]) => {
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

  const canManage = workspace?.permissions?.includes('settings.manage') ?? false;
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

  return <div className="page workspace-console-page">
    <div className="page-heading page-heading--split"><div><span className="page-kicker">Workspace administration</span><h2>Settings</h2><p>Workspace-owned configuration, access, security, developer controls, billing, and white label.</p></div><Badge tone="brand">{workspace.plan} plan</Badge></div>
    <div className="workspace-console-layout">
      <WorkspaceSettingsNavigation active={section} onSelect={(next) => navigate(`/workspace/settings/${next}`)} />
      <div className="workspace-console-content">
        {section === 'general' ? <WorkspaceGeneralSettings workspace={workspace} bundle={bundle} disabled={!canManage || saving} onWorkspace={setWorkspace} onBundle={setBundle} onSave={() => void save(
          async () => {
            const updated = await workspaceApi.update({ name: workspace.name, slug: workspace.slug, preferences: workspace.preferences });
            await workspaceSettingsApi.saveGeneral(bundle.general);
            return updated;
          }, setWorkspace, 'Workspace general settings saved')} /> : null}
        {section === 'members' ? <WorkspaceMembersSettings workspace={workspace} /> : null}
        {section === 'roles' ? <WorkspaceRolesSettings value={bundle.roles} catalog={capabilities} disabled={saving || !(workspace.permissions?.includes('roles.manage') ?? false)} onChange={(roles) => setBundle({ ...bundle, roles })} onSave={() => void save(() => workspaceSettingsApi.saveRoles(bundle.roles), (roles) => setBundle({ ...bundle, roles }), 'Roles saved')} /> : null}
        {section === 'teams' ? <WorkspaceTeamsSettings value={bundle.teams} roles={bundle.roles} disabled={saving || !(workspace.permissions?.includes('teams.manage') ?? false)} onChange={(teams) => setBundle({ ...bundle, teams })} onSave={() => void save(() => workspaceSettingsApi.saveTeams(bundle.teams), (teams) => setBundle({ ...bundle, teams }), 'Teams saved')} /> : null}
        {section === 'security' ? <WorkspaceSecuritySettings bundle={bundle} disabled={!canManage || saving} onBundle={setBundle} onSave={() => void save(() => workspaceSettingsApi.saveSecurity(bundle.security), (security) => setBundle({ ...bundle, security }), 'Security policy saved')} /> : null}
        {section === 'notifications' ? <WorkspaceNotificationsSettings bundle={bundle} disabled={!canManage || saving} onBundle={setBundle} onSave={() => void save(() => workspaceSettingsApi.saveNotifications(bundle.notifications), (notifications) => setBundle({ ...bundle, notifications }), 'Notification settings saved')} /> : null}
        {section === 'channels' ? <LinkSection title="Workspace channels" description="Channel connections remain owned by the existing channel pipeline. Manage them without duplicating connection logic." href="/integrations" action="Open channels and integrations" /> : null}
        {section === 'integrations' ? <LinkSection title="Workspace integrations" description="CRM, WhatsApp, and other integrations keep using the existing integration services and workspace scoping." href="/integrations" action="Open integrations" /> : null}
        {section === 'developer' ? <WorkspaceDeveloperSettings workspace={workspace} bundle={bundle} disabled={!canManage || saving} onBundle={setBundle} onSave={() => void save(() => workspaceSettingsApi.saveDeveloper(bundle.developer), (developer) => setBundle({ ...bundle, developer }), 'Developer policy saved')} /> : null}
        {section === 'audit' ? <LinkSection title="Workspace audit" description="Administrative writes from this settings center are recorded in the existing audit pipeline." href="/audit" action="Open audit log" /> : null}
        {section === 'billing' ? <SubscriptionBillingPanel workspace={workspace} /> : null}
        {section === 'branding' ? <WorkspaceBrandingControlCenter bundle={bundle} onChange={setBundle} /> : null}
      </div>
    </div>
  </div>;
}

function LinkSection({ title, description, href, action }: { title: string; description: string; href: string; action: string }) {
  return <Card className="workspace-panel"><div className="workspace-panel__body"><h3>{title}</h3><p>{description}</p><a className="button button--primary button--md" href={href}>{action}</a></div></Card>;
}
