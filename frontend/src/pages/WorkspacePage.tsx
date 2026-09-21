import {
  Building2, Mail, ShieldCheck,
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
import { WorkspaceGeneralPanel } from '@/features/workspace/general/WorkspaceGeneralPanel';
import { workspaceApi, type WorkspaceSettings } from '@/lib/workspace-api';
import '@/pages/WorkspaceTeam.css';

export function WorkspacePage() {
  const { session } = useAuth();
  const { pushToast } = useToast();
  const [params, setParams] = useSearchParams();
  const section = params.get('section') ?? 'workspace';
  const [workspace, setWorkspace] = useState<WorkspaceSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [loadingError, setLoadingError] = useState<string | null>(null);
  const [loadRevision, setLoadRevision] = useState(0);

  useEffect(() => {
    let active = true;
    setLoadingError(null);
    void workspaceApi.get().then((result) => {
      if (active) setWorkspace(result);
    }).catch((error: unknown) => {
      if (active) setLoadingError(error instanceof Error ? error.message : 'Workspace settings could not be loaded');
    });
    return () => { active = false; };
  }, [loadRevision]);
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

  async function saveSecurity() {
    if (!workspace) return;
    setSaving(true);
    try {
      const saved = await workspaceApi.update({ security: workspace.security });
      setWorkspace(saved); pushToast('Security settings saved');
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Security settings could not be saved', 'error');
    } finally { setSaving(false); }
  }

  if (!workspace) return loadingError ? <div className="page workspace-console-page">
    <Card className="workspace-panel">
      <div className="workspace-panel__body">
        <h2>Workspace settings unavailable</h2>
        <p role="alert">{loadingError}</p>
        <Button type="button" onClick={() => setLoadRevision((value) => value + 1)}>Retry loading workspace</Button>
      </div>
    </Card>
  </div> : <PageLoader />;

  return <div className="page workspace-console-page">
    <div className="page-heading page-heading--split"><div><span className="page-kicker">Administration</span><h2>Workspace</h2><p>Manage your organization, access, security, branding, and plan.</p></div><Badge tone="brand">{workspace.plan} plan</Badge></div>
    <div className="workspace-console-layout">
      <WorkspaceNavigation active={section} onSelect={(id) => setParams(id === 'workspace' ? {} : { section: id })} />
      <div className="workspace-console-content">
        {section === 'workspace' ? <WorkspaceGeneralPanel workspace={workspace} setWorkspace={setWorkspace} onSave={saveProfile} saving={saving} ownerInitial={ownerInitial} /> : null}

        {section === 'team' ? <WorkspaceTeamPanel workspace={workspace} /> : null}

        {section === 'developer' ? <WorkspaceAPIKeysPanel workspace={workspace} /> : null}

        {section === 'security' ? <Card className="workspace-panel"><PanelHeading icon={ShieldCheck} title="Security controls" description="Apply workspace-wide protection and manage your own sign-in security." />
          <div className="workspace-panel__body">
            <Switch checked={workspace.security.sensitiveDataMasking} onChange={(value) => setWorkspace({ ...workspace, security: { ...workspace.security, sensitiveDataMasking: value } })} label="Sensitive data masking" description="Redact credentials, payment details, and government IDs before chat persistence and model use." />
            <Switch checked={false} onChange={() => undefined} disabled label="Require MFA for all workspace members" description="Workspace-wide MFA enforcement is a separate policy feature. Configure your own account MFA below." />
            <Switch checked={false} onChange={() => undefined} disabled label="Weekly security digest" description="Digest delivery is not enabled in this deployment." />
            <Field label="Security contact"><div className="icon-input"><Mail /><input type="email" value={workspace.security.securityContact ?? ''} placeholder={session?.user.email} onChange={(event) => setWorkspace({ ...workspace, security: { ...workspace.security, securityContact: event.target.value || null } })} /></div></Field>
            <div className="workspace-panel__actions"><Button onClick={() => void saveSecurity()} disabled={saving}>{saving ? 'Saving…' : 'Save security'}</Button></div>
            <MFASecurityPanel />
          </div>
        </Card> : null}

        {section === 'billing' ? <SubscriptionBillingPanel workspace={workspace} /> : null}
      </div>
    </div>
  </div>;
}

function PanelHeading({ icon: Icon, title, description, action }: { icon: typeof Building2; title: string; description: string; action?: ReactNode }) { return <div className="workspace-panel__heading"><span><Icon /></span><div><h3>{title}</h3><p>{description}</p></div>{action}</div>; }
