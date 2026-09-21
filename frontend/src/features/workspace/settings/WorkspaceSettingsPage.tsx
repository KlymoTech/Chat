import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Badge, Button, Card, Field, PageLoader, Switch } from '@/components/ui';
import { useToast } from '@/components/providers';
import { WorkspaceAPIKeysPanel } from '@/components/WorkspaceAPIKeysPanel';
import { WorkspaceTeamPanel } from '@/components/WorkspaceTeamPanel';
import { SubscriptionBillingPanel } from '@/components/SubscriptionBillingPanel';
import { MFASecurityPanel } from '@/components/mfa-security-panel';
import { workspaceApi, type WorkspaceSettings } from '@/lib/workspace-api';
import { WorkspaceGeneralSettings } from './WorkspaceGeneralSettings';
import { WorkspaceSettingsNavigation } from './WorkspaceSettingsNavigation';
import { WorkspaceBrandingSettings } from './WorkspaceBrandingSettings';
import { workspaceSettingsApi, type CapabilityCatalog, type CustomRole, type SettingsSection, type WorkspaceSettingsBundle, type WorkspaceTeam } from './workspaceSettings.api';
import '@/pages/WorkspaceTeam.css';

const sections: SettingsSection[] = ['general','members','roles','teams','security','notifications','channels','integrations','developer','audit','billing','branding'];

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
    Promise.all([workspaceApi.get(), workspaceSettingsApi.get(), workspaceSettingsApi.capabilities()]).then(([workspaceValue, settingsValue, catalog]) => {
      if (!current) return; setWorkspace(workspaceValue); setBundle(settingsValue); setCapabilities(catalog); setError('');
    }).catch((reason: unknown) => { if (current) setError(reason instanceof Error ? reason.message : 'Workspace settings could not be loaded'); });
    return () => { current = false; };
  }, []);

  const canManage = workspace?.permissions?.includes('settings.manage') ?? false;
  async function save<T>(work: () => Promise<T>, apply: (value: T) => void, message: string) {
    setSaving(true);
    try { const value = await work(); apply(value); pushToast(message); }
    catch (reason) { pushToast(reason instanceof Error ? reason.message : 'Settings could not be saved', 'error'); }
    finally { setSaving(false); }
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
            await workspaceSettingsApi.saveGeneral(bundle.general); return updated;
          }, setWorkspace, 'Workspace general settings saved')} /> : null}
        {section === 'members' ? <WorkspaceTeamPanel workspace={workspace} /> : null}
        {section === 'roles' ? <RolesSection value={bundle.roles.customRoles} catalog={capabilities} disabled={saving || !(workspace.permissions?.includes('roles.manage') ?? false)} onChange={(customRoles) => setBundle({ ...bundle, roles: { ...bundle.roles, customRoles } })} onSave={() => void save(() => workspaceSettingsApi.saveRoles(bundle.roles), (roles) => setBundle({ ...bundle, roles }), 'Roles saved')} /> : null}
        {section === 'teams' ? <TeamsSection value={bundle.teams.teams} disabled={saving || !(workspace.permissions?.includes('teams.manage') ?? false)} onChange={(teams) => setBundle({ ...bundle, teams: { teams } })} onSave={() => void save(() => workspaceSettingsApi.saveTeams(bundle.teams), (teams) => setBundle({ ...bundle, teams }), 'Teams saved')} /> : null}
        {section === 'security' ? <SecuritySection workspace={workspace} bundle={bundle} disabled={!canManage || saving} onBundle={setBundle} onSave={() => void save(() => workspaceSettingsApi.saveSecurity(bundle.security), (security) => setBundle({ ...bundle, security }), 'Security policy saved')} /> : null}
        {section === 'notifications' ? <NotificationsSection bundle={bundle} disabled={!canManage || saving} onBundle={setBundle} onSave={() => void save(() => workspaceSettingsApi.saveNotifications(bundle.notifications), (notifications) => setBundle({ ...bundle, notifications }), 'Notification settings saved')} /> : null}
        {section === 'channels' ? <LinkSection title="Workspace channels" description="Channel connections remain owned by the existing channel pipeline. Manage them without duplicating connection logic." href="/integrations" action="Open channels and integrations" /> : null}
        {section === 'integrations' ? <LinkSection title="Workspace integrations" description="CRM, WhatsApp, and other integrations keep using the existing integration services and workspace scoping." href="/integrations" action="Open integrations" /> : null}
        {section === 'developer' ? <DeveloperSection workspace={workspace} bundle={bundle} disabled={!canManage || saving} onBundle={setBundle} onSave={() => void save(() => workspaceSettingsApi.saveDeveloper(bundle.developer), (developer) => setBundle({ ...bundle, developer }), 'Developer policy saved')} /> : null}
        {section === 'audit' ? <LinkSection title="Workspace audit" description="Administrative writes from this settings center are recorded in the existing audit pipeline." href="/audit" action="Open audit log" /> : null}
        {section === 'billing' ? <SubscriptionBillingPanel workspace={workspace} /> : null}
        {section === 'branding' ? <WorkspaceBrandingSettings bundle={bundle} onChange={setBundle} /> : null}
      </div>
    </div>
  </div>;
}

function RolesSection({ value, catalog, disabled, onChange, onSave }: { value: CustomRole[]; catalog: CapabilityCatalog; disabled: boolean; onChange: (value: CustomRole[]) => void; onSave: () => void }) {
  function add() { onChange([...value, { id: crypto.randomUUID(), name: 'Custom role', description: '', permissions: ['workspace.view'], resources: { selected: {}, conversationScope: 'all' } }]); }
  return <Card className="workspace-panel"><div className="workspace-panel__body"><div className="page-heading page-heading--split"><div><h3>Roles & permissions</h3><p>Capabilities are explicit permissions rather than page names. Built-in roles stay compatible with the current access policy.</p></div><Button disabled={disabled} onClick={add}>Add custom role</Button></div>
    <div className="setup-resource"><strong>Built-in roles</strong><p>{Object.keys(catalog.builtinRoles).join(', ')}</p></div>
    {value.map((role, index) => <div className="setup-resource" key={role.id}><div className="two-fields"><Field label="Role name"><input disabled={disabled} value={role.name} onChange={(e) => onChange(value.map((item, i) => i === index ? { ...item, name: e.target.value } : item))} /></Field><Field label="Conversation scope"><select disabled={disabled} value={role.resources.conversationScope} onChange={(e) => onChange(value.map((item, i) => i === index ? { ...item, resources: { ...item.resources, conversationScope: e.target.value as 'all' | 'assigned' | 'team' } } : item))}><option value="all">All</option><option value="team">Team</option><option value="assigned">Assigned</option></select></Field></div><Field label="Description"><input disabled={disabled} value={role.description} onChange={(e) => onChange(value.map((item, i) => i === index ? { ...item, description: e.target.value } : item))} /></Field><Field label="Permissions (comma separated)"><textarea disabled={disabled} value={role.permissions.join(', ')} onChange={(e) => onChange(value.map((item, i) => i === index ? { ...item, permissions: e.target.value.split(',').map((part) => part.trim()).filter(Boolean) } : item))} /></Field><Button variant="danger" disabled={disabled} onClick={() => onChange(value.filter((_, i) => i !== index))}>Delete role</Button></div>)}
    <div className="workspace-panel__actions"><Button disabled={disabled} onClick={onSave}>Save roles</Button></div>
  </div></Card>;
}

function TeamsSection({ value, disabled, onChange, onSave }: { value: WorkspaceTeam[]; disabled: boolean; onChange: (value: WorkspaceTeam[]) => void; onSave: () => void }) {
  const emptyHours = useMemo(() => ({ enabled: false, timezone: 'Asia/Kolkata', schedule: {} }), []);
  function add() { onChange([...value, { id: crypto.randomUUID(), name: 'New team', description: '', memberIds: [], managerIds: [], roleIds: [], queueIds: [], agentIds: [], channelIds: [], businessHours: emptyHours, escalationRule: '' }]); }
  return <Card className="workspace-panel"><div className="workspace-panel__body"><div className="page-heading page-heading--split"><div><h3>Teams</h3><p>Teams own routing, members, managers, agents, channels, business hours, and escalation rules.</p></div><Button disabled={disabled} onClick={add}>Add team</Button></div>
    {value.map((team, index) => <div className="setup-resource" key={team.id}><div className="two-fields"><Field label="Team name"><input disabled={disabled} value={team.name} onChange={(e) => onChange(value.map((item, i) => i === index ? { ...item, name: e.target.value } : item))} /></Field><Field label="Description"><input disabled={disabled} value={team.description} onChange={(e) => onChange(value.map((item, i) => i === index ? { ...item, description: e.target.value } : item))} /></Field></div><Field label="Escalation rule"><input disabled={disabled} value={team.escalationRule} onChange={(e) => onChange(value.map((item, i) => i === index ? { ...item, escalationRule: e.target.value } : item))} /></Field><Button variant="danger" disabled={disabled} onClick={() => onChange(value.filter((_, i) => i !== index))}>Delete team</Button></div>)}
    <div className="workspace-panel__actions"><Button disabled={disabled} onClick={onSave}>Save teams</Button></div>
  </div></Card>;
}

function SecuritySection({ bundle, disabled, onBundle, onSave }: { workspace: WorkspaceSettings; bundle: WorkspaceSettingsBundle; disabled: boolean; onBundle: (value: WorkspaceSettingsBundle) => void; onSave: () => void }) {
  const security = bundle.security;
  return <><Card className="workspace-panel"><div className="workspace-panel__body"><h3>Workspace security</h3>
    <Switch checked={security.sensitiveDataMasking} disabled={disabled} onChange={(value) => onBundle({ ...bundle, security: { ...security, sensitiveDataMasking: value } })} label="Sensitive data masking" />
    <Field label="MFA enforcement"><select disabled={disabled} value={security.mfaEnforcement} onChange={(e) => onBundle({ ...bundle, security: { ...security, mfaEnforcement: e.target.value as 'optional' | 'admins' | 'all' } })}><option value="optional">Optional</option><option value="admins">Administrators</option><option value="all">All members</option></select></Field>
    <div className="two-fields"><Field label="Session timeout (minutes)"><input type="number" min={15} disabled={disabled} value={security.sessionTimeoutMinutes} onChange={(e) => onBundle({ ...bundle, security: { ...security, sessionTimeoutMinutes: Number(e.target.value) } })} /></Field><Field label="Password minimum length"><input type="number" min={8} disabled={disabled} value={security.passwordMinLength} onChange={(e) => onBundle({ ...bundle, security: { ...security, passwordMinLength: Number(e.target.value) } })} /></Field></div>
    <Field label="Security contact"><input type="email" disabled={disabled} value={security.securityContact ?? ''} onChange={(e) => onBundle({ ...bundle, security: { ...security, securityContact: e.target.value || null } })} /></Field>
    <Switch checked={security.webhookSigningRequired} disabled={disabled} onChange={(value) => onBundle({ ...bundle, security: { ...security, webhookSigningRequired: value } })} label="Require webhook signing" />
    <Switch checked={security.securityNotifications} disabled={disabled} onChange={(value) => onBundle({ ...bundle, security: { ...security, securityNotifications: value } })} label="Security notifications" />
    <div className="workspace-panel__actions"><Button disabled={disabled} onClick={onSave}>Save security policy</Button></div>
  </div></Card><MFASecurityPanel /></>;
}

function NotificationsSection({ bundle, disabled, onBundle, onSave }: { bundle: WorkspaceSettingsBundle; disabled: boolean; onBundle: (value: WorkspaceSettingsBundle) => void; onSave: () => void }) {
  const value = bundle.notifications;
  const toggle = (key: keyof typeof value, checked: boolean) => onBundle({ ...bundle, notifications: { ...value, [key]: checked } });
  return <Card className="workspace-panel"><div className="workspace-panel__body"><h3>Notifications</h3>{(['memberChanges','securityAlerts','billingAlerts','channelFailures','integrationFailures','weeklyDigest'] as const).map((key) => <Switch key={key} disabled={disabled} checked={value[key] as boolean} onChange={(checked) => toggle(key, checked)} label={key.replace(/([A-Z])/g, ' $1')} />)}<Field label="Recipients (comma separated)"><input disabled={disabled} value={value.recipients.join(', ')} onChange={(e) => onBundle({ ...bundle, notifications: { ...value, recipients: e.target.value.split(',').map((item) => item.trim()).filter(Boolean) } })} /></Field><div className="workspace-panel__actions"><Button disabled={disabled} onClick={onSave}>Save notifications</Button></div></div></Card>;
}

function DeveloperSection({ workspace, bundle, disabled, onBundle, onSave }: { workspace: WorkspaceSettings; bundle: WorkspaceSettingsBundle; disabled: boolean; onBundle: (value: WorkspaceSettingsBundle) => void; onSave: () => void }) {
  const developer = bundle.developer;
  return <><Card className="workspace-panel"><div className="workspace-panel__body"><h3>Developer policy</h3><Switch checked={developer.sandboxMode} disabled={disabled} onChange={(sandboxMode) => onBundle({ ...bundle, developer: { ...developer, sandboxMode } })} label="Sandbox / test mode" /><Switch checked={developer.webhookSigningEnabled} disabled={disabled} onChange={(webhookSigningEnabled) => onBundle({ ...bundle, developer: { ...developer, webhookSigningEnabled } })} label="Webhook signing" /><div className="two-fields"><Field label="Rate limit / minute"><input type="number" disabled={disabled} value={developer.rateLimitPerMinute} onChange={(e) => onBundle({ ...bundle, developer: { ...developer, rateLimitPerMinute: Number(e.target.value) } })} /></Field><Field label="Webhook retry limit"><input type="number" disabled={disabled} value={developer.webhookRetryLimit} onChange={(e) => onBundle({ ...bundle, developer: { ...developer, webhookRetryLimit: Number(e.target.value) } })} /></Field></div><Field label="Webhook events (comma separated)"><input disabled={disabled} value={developer.webhookEvents.join(', ')} onChange={(e) => onBundle({ ...bundle, developer: { ...developer, webhookEvents: e.target.value.split(',').map((item) => item.trim()).filter(Boolean) } })} /></Field><div className="workspace-panel__actions"><Button disabled={disabled} onClick={onSave}>Save developer policy</Button></div></div></Card><WorkspaceAPIKeysPanel workspace={workspace} /></>;
}

function LinkSection({ title, description, href, action }: { title: string; description: string; href: string; action: string }) { return <Card className="workspace-panel"><div className="workspace-panel__body"><h3>{title}</h3><p>{description}</p><a className="button button--primary button--md" href={href}>{action}</a></div></Card>; }
