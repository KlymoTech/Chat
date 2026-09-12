import {
  Building2, GraduationCap, Mail, ShieldCheck,
} from 'lucide-react';
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { MFASecurityPanel } from '@/components/mfa-security-panel';
import { useAuth, useToast } from '@/components/providers';
import { SubscriptionBillingPanel } from '@/components/SubscriptionBillingPanel';
import { Button, Badge, Card, Field, PageLoader, Switch } from '@/components/ui';
import { WorkspaceAPIKeysPanel } from '@/components/WorkspaceAPIKeysPanel';
import { WorkspaceNavigation } from '@/components/workspace-navigation';
import { WorkspaceTeamPanel } from '@/components/WorkspaceTeamPanel';
import {
  educationSalesSettingsApi,
  type EducationSalesRoutingSettings,
} from '@/lib/education-sales-settings-api';
import { workspaceApi, type WorkspaceSettings } from '@/lib/workspace-api';
import '@/pages/WorkspaceTeam.css';

export function WorkspacePage() {
  const { session } = useAuth();
  const { pushToast } = useToast();
  const [params, setParams] = useSearchParams();
  const section = params.get('section') ?? 'workspace';
  const [workspace, setWorkspace] = useState<WorkspaceSettings | null>(null);
  const [educationSales, setEducationSales] = useState<EducationSalesRoutingSettings>({
    createUpsellLeads: false,
  });
  const [saving, setSaving] = useState(false);
  const [savingEducationSales, setSavingEducationSales] = useState(false);
  const [masking, setMasking] = useState(true);
  const [digest, setDigest] = useState(true);

  useEffect(() => {
    void workspaceApi.get().then(setWorkspace);
    void educationSalesSettingsApi.get()
      .then(setEducationSales)
      .catch(() => setEducationSales({ createUpsellLeads: false }));
  }, []);
  const ownerInitial = useMemo(() => session?.user.name.charAt(0).toUpperCase() ?? 'N', [session]);

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    if (!workspace) return;
    setSaving(true);
    try {
      const saved = await workspaceApi.update({
        name: workspace.name,
        slug: workspace.slug,
        preferences: workspace.preferences,
        educationCreateUpsellLeads: workspace.educationCreateUpsellLeads,
      });
      setWorkspace(saved); pushToast('Workspace settings saved');
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Workspace settings could not be saved', 'error');
    } finally { setSaving(false); }
  }

  async function saveEducationSalesRouting() {
    setSavingEducationSales(true);
    try {
      const saved = await educationSalesSettingsApi.update(educationSales);
      setEducationSales(saved);
      pushToast(saved.createUpsellLeads
        ? 'Education sales Lead routing enabled'
        : 'Education sales Lead routing disabled');
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Education sales routing could not be saved', 'error');
    } finally {
      setSavingEducationSales(false);
    }
  }

  if (!workspace) return <PageLoader />;

  return <div className="page workspace-console-page">
    <div className="page-heading page-heading--split"><div><span className="page-kicker">Administration</span><h2>Workspace</h2><p>Manage your organization, access, security, branding, and plan.</p></div><Badge tone="brand">{workspace.plan} plan</Badge></div>
    <div className="workspace-console-layout">
      <WorkspaceNavigation active={section} onSelect={(id) => setParams(id === 'workspace' ? {} : { section: id })} />
      <div className="workspace-console-content">
        {section === 'workspace' ? <>
          <form onSubmit={saveProfile}>
            <Card className="workspace-panel"><PanelHeading icon={Building2} title="Workspace profile" description="Organization details and regional preferences shared across the workspace." />
              <div className="workspace-panel__body">
                <div className="workspace-profile-mark">{workspace.whiteLabel.logoDataUrl ? <img src={workspace.whiteLabel.logoDataUrl} alt="Workspace logo" /> : ownerInitial}</div>
                <div className="two-fields"><Field label="Workspace name" htmlFor="workspace-name"><input id="workspace-name" value={workspace.name} onChange={(event) => setWorkspace({ ...workspace, name: event.target.value })} /></Field><Field label="Workspace slug" htmlFor="workspace-slug"><div className="prefix-input"><span>app.northstar.ai/</span><input id="workspace-slug" value={workspace.slug} onChange={(event) => setWorkspace({ ...workspace, slug: event.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '') })} /></div></Field></div>
                <div className="two-fields"><Field label="Timezone"><select value={workspace.preferences.timezone} onChange={(event) => setWorkspace({ ...workspace, preferences: { ...workspace.preferences, timezone: event.target.value } })}><option>Asia/Calcutta</option><option>UTC</option><option>America/New_York</option><option>Europe/London</option></select></Field><Field label="Date format"><select value={workspace.preferences.dateFormat} onChange={(event) => setWorkspace({ ...workspace, preferences: { ...workspace.preferences, dateFormat: event.target.value as WorkspaceSettings['preferences']['dateFormat'] } })}><option>DD/MM/YYYY</option><option>MM/DD/YYYY</option><option>YYYY-MM-DD</option></select></Field></div>
                <Field label="Default workspace language"><select value={workspace.preferences.defaultLanguage} onChange={(event) => setWorkspace({ ...workspace, preferences: { ...workspace.preferences, defaultLanguage: event.target.value } })}><option>English</option><option>Hindi</option><option>Spanish</option><option>French</option><option>German</option><option>Arabic</option></select></Field>
                <div className="workspace-panel__actions"><Button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save workspace'}</Button></div>
              </div>
            </Card>
          </form>

          <Card className="workspace-panel"><PanelHeading icon={GraduationCap} title="Education sales routing" description="Keep Education conversations out of the Lead pipeline by default, with an explicit opt-in for verified Student sales opportunities." />
            <div className="workspace-panel__body">
              <Switch
                checked={educationSales.createUpsellLeads}
                onChange={(createUpsellLeads) => setEducationSales({ createUpsellLeads })}
                label="Create upsell leads from Education Agents"
                description="When enabled, teammates can explicitly resolve an authorized Education conversation as sales intent and reuse the existing Lead + CRM pipeline. Normal Education Resolve still creates no Lead."
              />
              <div className="workspace-panel__actions"><Button onClick={() => void saveEducationSalesRouting()} disabled={savingEducationSales}>{savingEducationSales ? 'Saving…' : 'Save Education routing'}</Button></div>
            </div>
          </Card>
        </> : null}

        {section === 'team' ? <WorkspaceTeamPanel workspace={workspace} /> : null}

        {section === 'developer' ? <WorkspaceAPIKeysPanel workspace={workspace} /> : null}

        {section === 'security' ? <Card className="workspace-panel"><PanelHeading icon={ShieldCheck} title="Security controls" description="Apply workspace-wide protection and manage your own sign-in security." />
          <div className="workspace-panel__body">
            <Switch checked={masking} onChange={setMasking} label="Sensitive data masking" description="Redact credentials, payment details, and government IDs from logs." />
            <Switch checked={false} onChange={() => undefined} disabled label="Require MFA for all workspace members" description="Workspace-wide MFA enforcement is a separate policy feature. Configure your own account MFA below." />
            <Switch checked={digest} onChange={setDigest} label="Weekly security digest" description="Email workspace owners about access and configuration changes." />
            <Field label="Security contact"><div className="icon-input"><Mail /><input defaultValue={session?.user.email} /></div></Field>
            <div className="workspace-panel__actions"><Button onClick={() => pushToast('Security settings saved')}>Save security</Button></div>
            <MFASecurityPanel />
          </div>
        </Card> : null}

        {section === 'billing' ? <SubscriptionBillingPanel workspace={workspace} /> : null}
      </div>
    </div>
  </div>;
}

function PanelHeading({ icon: Icon, title, description, action }: { icon: typeof Building2; title: string; description: string; action?: ReactNode }) { return <div className="workspace-panel__heading"><span><Icon /></span><div><h3>{title}</h3><p>{description}</p></div>{action}</div>; }
