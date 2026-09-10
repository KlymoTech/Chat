import {
  Building2, Check, Copy, CreditCard, KeyRound, LockKeyhole, Mail, Plus, ShieldCheck,
  Sparkles, Trash2, UserPlus, UsersRound,
} from 'lucide-react';
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { MFASecurityPanel } from '@/components/mfa-security-panel';
import { WorkspaceNavigation } from '@/components/workspace-navigation';
import { useAuth, useToast } from '@/components/providers';
import { Badge, Button, Card, Field, Modal, PageLoader, Switch } from '@/components/ui';
import { readStorage, writeStorage } from '@/lib/storage';
import { workspaceApi, type WorkspaceSettings } from '@/lib/workspace-api';

interface LocalMember { id: string; name: string; email: string; role: 'Admin' | 'Member' | 'Analyst'; status: 'Active' | 'Invited' }
interface LocalKey { id: string; name: string; prefix: string; createdAt: string }

const MEMBERS_KEY = 'northstar.workspace.members';
const KEYS_KEY = 'northstar.workspace.api-keys';

export function WorkspacePage() {
  const { session } = useAuth();
  const { pushToast } = useToast();
  const [params, setParams] = useSearchParams();
  const section = params.get('section') ?? 'workspace';
  const [workspace, setWorkspace] = useState<WorkspaceSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState<LocalMember['role']>('Member');
  const [members, setMembers] = useState<LocalMember[]>(() => readStorage(MEMBERS_KEY, []));
  const [keys, setKeys] = useState<LocalKey[]>(() => readStorage(KEYS_KEY, []));
  const [newSecret, setNewSecret] = useState('');
  const [masking, setMasking] = useState(true);
  const [digest, setDigest] = useState(true);

  useEffect(() => { void workspaceApi.get().then(setWorkspace); }, []);
  const ownerInitial = useMemo(() => session?.user.name.charAt(0).toUpperCase() ?? 'N', [session]);

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    if (!workspace) return;
    setSaving(true);
    try {
      const saved = await workspaceApi.update({ name: workspace.name, slug: workspace.slug, preferences: workspace.preferences });
      setWorkspace(saved); pushToast('Workspace settings saved');
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Workspace settings could not be saved', 'error');
    } finally { setSaving(false); }
  }

  function invite(event: FormEvent) {
    event.preventDefault();
    const email = inviteEmail.trim().toLowerCase();
    if (!email || !email.includes('@')) { pushToast('Enter a valid email address', 'error'); return; }
    const next = [{ id: crypto.randomUUID(), name: email.split('@')[0]!, email, role: inviteRole, status: 'Invited' as const }, ...members];
    setMembers(next); writeStorage(MEMBERS_KEY, next); setInviteEmail(''); setInviteOpen(false); pushToast(`Invitation sent to ${email}`);
  }

  function createKey() {
    const raw = `nsk_live_${crypto.randomUUID().replaceAll('-', '')}`;
    const item = { id: crypto.randomUUID(), name: `Production ${keys.length + 1}`, prefix: `${raw.slice(0, 14)}••••${raw.slice(-4)}`, createdAt: new Date().toISOString() };
    const next = [item, ...keys]; setKeys(next); writeStorage(KEYS_KEY, next); setNewSecret(raw);
  }

  function revokeKey(id: string) {
    const next = keys.filter((item) => item.id !== id); setKeys(next); writeStorage(KEYS_KEY, next); pushToast('API key revoked');
  }

  if (!workspace) return <PageLoader />;

  return <div className="page workspace-console-page">
    <div className="page-heading page-heading--split"><div><span className="page-kicker">Administration</span><h2>Workspace</h2><p>Manage your organization, access, security, branding, and plan.</p></div><Badge tone="brand">{workspace.plan} plan</Badge></div>
    <div className="workspace-console-layout">
      <WorkspaceNavigation active={section} onSelect={(id) => setParams(id === 'workspace' ? {} : { section: id })} />
      <div className="workspace-console-content">
        {section === 'workspace' ? <form onSubmit={saveProfile}>
          <Card className="workspace-panel"><PanelHeading icon={Building2} title="Workspace profile" description="Organization details and regional preferences shared across the workspace." />
            <div className="workspace-panel__body">
              <div className="workspace-profile-mark">{workspace.whiteLabel.logoDataUrl ? <img src={workspace.whiteLabel.logoDataUrl} alt="Workspace logo" /> : ownerInitial}</div>
              <div className="two-fields"><Field label="Workspace name" htmlFor="workspace-name"><input id="workspace-name" value={workspace.name} onChange={(event) => setWorkspace({ ...workspace, name: event.target.value })} /></Field><Field label="Workspace slug" htmlFor="workspace-slug"><div className="prefix-input"><span>app.northstar.ai/</span><input id="workspace-slug" value={workspace.slug} onChange={(event) => setWorkspace({ ...workspace, slug: event.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '') })} /></div></Field></div>
              <div className="two-fields"><Field label="Timezone"><select value={workspace.preferences.timezone} onChange={(event) => setWorkspace({ ...workspace, preferences: { ...workspace.preferences, timezone: event.target.value } })}><option>Asia/Calcutta</option><option>UTC</option><option>America/New_York</option><option>Europe/London</option></select></Field><Field label="Date format"><select value={workspace.preferences.dateFormat} onChange={(event) => setWorkspace({ ...workspace, preferences: { ...workspace.preferences, dateFormat: event.target.value as WorkspaceSettings['preferences']['dateFormat'] } })}><option>DD/MM/YYYY</option><option>MM/DD/YYYY</option><option>YYYY-MM-DD</option></select></Field></div>
              <Field label="Default workspace language"><select value={workspace.preferences.defaultLanguage} onChange={(event) => setWorkspace({ ...workspace, preferences: { ...workspace.preferences, defaultLanguage: event.target.value } })}><option>English</option><option>Hindi</option><option>Spanish</option><option>French</option><option>German</option><option>Arabic</option></select></Field>
              <div className="workspace-panel__actions"><Button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save workspace'}</Button></div>
            </div>
          </Card>
        </form> : null}

        {section === 'team' ? <Card className="workspace-panel"><PanelHeading icon={UsersRound} title="Team members" description="Invite teammates and assign the right level of workspace access." action={<Button icon={UserPlus} onClick={() => setInviteOpen(true)}>Invite member</Button>} />
          <div className="workspace-member-list"><MemberRow initial={ownerInitial} name={session?.user.name ?? 'Workspace owner'} email={session?.user.email ?? ''} role="Owner" status="Active" />{members.map((member) => <MemberRow key={member.id} initial={member.name.charAt(0).toUpperCase()} name={member.name} email={member.email} role={member.role} status={member.status} />)}</div>
        </Card> : null}

        {section === 'developer' ? <Card className="workspace-panel"><PanelHeading icon={KeyRound} title="API keys" description="Create and revoke credentials used by your server-side integrations." action={<Button icon={Plus} onClick={createKey}>Create secret key</Button>} />
          {newSecret ? <div className="workspace-secret"><LockKeyhole /><div><strong>Copy this key now</strong><small>For security, it will not be shown again.</small><code>{newSecret}</code></div><button type="button" className="icon-button" aria-label="Copy new API key" onClick={() => void navigator.clipboard.writeText(newSecret).then(() => pushToast('Secret key copied'))}><Copy /></button><button type="button" className="icon-button" aria-label="Hide new API key" onClick={() => setNewSecret('')}><Check /></button></div> : null}
          <div className="workspace-key-list">{keys.length ? keys.map((key) => <div key={key.id}><span><strong>{key.name}</strong><small>Created {new Date(key.createdAt).toLocaleDateString()}</small></span><code>{key.prefix}</code><button type="button" className="icon-button danger-hover" onClick={() => revokeKey(key.id)} aria-label={`Revoke ${key.name}`}><Trash2 /></button></div>) : <div className="workspace-empty-row"><KeyRound /><span><strong>No API keys yet</strong><small>Create a key when you are ready to connect your backend.</small></span></div>}</div>
        </Card> : null}

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

        {section === 'billing' ? <><Card className="workspace-panel"><PanelHeading icon={CreditCard} title="Plan & billing" description="Review usage, limits, and billing information." action={<Badge tone="brand">Business</Badge>} /><div className="workspace-plan-grid"><Usage label="Conversations" value="1,892 / 5,000" width="38%" /><Usage label="AI agents" value="4 / 10" width="40%" /><Usage label="Team members" value={`${Math.max(workspace.memberCount, members.length + 1)} / 20`} width="25%" /></div><div className="workspace-panel__actions workspace-panel__actions--border"><Button variant="secondary" onClick={() => pushToast('Billing portal will open after a payment provider is connected', 'info')}>Manage billing</Button><Button onClick={() => pushToast('Plan comparison opened', 'info')}>Compare plans</Button></div></Card>
          <Card className="workspace-upgrade-card"><Sparkles /><div><strong>Need more capacity?</strong><p>Upgrade limits without changing your agents, knowledge, or integrations.</p></div><Button variant="secondary" onClick={() => pushToast('Plan comparison opened', 'info')}>View plans</Button></Card></> : null}
      </div>
    </div>
    <Modal open={inviteOpen} onClose={() => setInviteOpen(false)} title="Invite a team member" description="They will receive an invitation to join this workspace." footer={<><Button variant="secondary" onClick={() => setInviteOpen(false)}>Cancel</Button><Button type="submit" form="workspace-invite-form">Send invitation</Button></>}><form id="workspace-invite-form" onSubmit={invite}><Field label="Email address" htmlFor="invite-email"><input id="invite-email" type="email" value={inviteEmail} onChange={(event) => setInviteEmail(event.target.value)} placeholder="name@company.com" autoFocus /></Field><Field label="Role"><select value={inviteRole} onChange={(event) => setInviteRole(event.target.value as LocalMember['role'])}><option>Admin</option><option>Member</option><option>Analyst</option></select></Field></form></Modal>
  </div>;
}

function PanelHeading({ icon: Icon, title, description, action }: { icon: typeof Building2; title: string; description: string; action?: ReactNode }) { return <div className="workspace-panel__heading"><span><Icon /></span><div><h3>{title}</h3><p>{description}</p></div>{action}</div>; }
function MemberRow({ initial, name, email, role, status }: { initial: string; name: string; email: string; role: string; status: string }) { return <div><span className="mini-avatar">{initial}</span><span><strong>{name}</strong><small>{email}</small></span><Badge tone={status === 'Active' ? 'success' : 'warning'}>{status}</Badge><Badge tone={role === 'Owner' ? 'purple' : 'neutral'}>{role}</Badge></div>; }
function Usage({ label, value, width }: { label: string; value: string; width: string }) { return <div><small>{label}</small><strong>{value}</strong><span><i style={{ width }} /></span></div>; }
