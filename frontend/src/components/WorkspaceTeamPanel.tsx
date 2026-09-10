import {
  CircleAlert,
  Clock3,
  Mail,
  Pencil,
  RefreshCw,
  ShieldCheck,
  Trash2,
  UserPlus,
  UsersRound,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import { useToast } from '@/components/providers';
import { Badge, Button, Card, Field, Modal, Switch } from '@/components/ui';
import { api } from '@/lib/api';
import {
  workspaceTeamApi,
  type WorkspaceAccessInput,
  type WorkspaceInvitation,
  type WorkspaceMember,
  type WorkspaceRole,
} from '@/lib/workspace-team-api';
import type { WorkspaceSettings } from '@/lib/workspace-api';
import type { Agent } from '@/types';

const ROLE_OPTIONS: Array<{ value: WorkspaceRole; label: string }> = [
  { value: 'workspace_admin', label: 'Workspace admin' },
  { value: 'manager', label: 'Manager' },
  { value: 'operator', label: 'Operator' },
  { value: 'analyst', label: 'Analyst' },
  { value: 'viewer', label: 'Viewer' },
];

interface AccessDraft extends WorkspaceAccessInput {
  email: string;
}

const emptyDraft: AccessDraft = {
  email: '',
  role: 'operator',
  allAgentsAccess: true,
  agentIds: [],
};

function roleLabel(role: WorkspaceRole): string {
  return ROLE_OPTIONS.find((item) => item.value === role)?.label ?? role;
}

function invitationTone(status: WorkspaceInvitation['status']) {
  if (status === 'pending') return 'warning' as const;
  if (status === 'expired' || status === 'revoked' || status === 'declined') return 'danger' as const;
  return 'success' as const;
}

export function WorkspaceTeamPanel({ workspace }: { workspace: WorkspaceSettings }) {
  const { pushToast } = useToast();
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [invitations, setInvitations] = useState<WorkspaceInvitation[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteDraft, setInviteDraft] = useState<AccessDraft>(emptyDraft);
  const [editing, setEditing] = useState<WorkspaceMember | null>(null);
  const [editDraft, setEditDraft] = useState<WorkspaceAccessInput>({
    role: 'operator',
    allAgentsAccess: true,
    agentIds: [],
  });
  const [submitting, setSubmitting] = useState(false);
  const [operationId, setOperationId] = useState('');

  const permissions = workspace.permissions ?? [];
  const canView = permissions.includes('*') || permissions.includes('members.view');
  const canManage = permissions.includes('*') || permissions.includes('members.manage');

  const load = useCallback(async () => {
    if (!canView) {
      setLoadError('Your workspace role does not include permission to view team membership.');
      setLoading(false);
      return;
    }
    setLoading(true);
    setLoadError('');
    try {
      const [nextMembers, nextInvitations, nextAgents] = await Promise.all([
        workspaceTeamApi.listMembers(),
        workspaceTeamApi.listInvitations(),
        canManage ? api.agents.list() : Promise.resolve([] as Agent[]),
      ]);
      setMembers(nextMembers);
      setInvitations(nextInvitations);
      setAgents(nextAgents);
    } catch (reason) {
      setLoadError(reason instanceof Error ? reason.message : 'Team membership could not be loaded.');
    } finally {
      setLoading(false);
    }
  }, [canManage, canView]);

  useEffect(() => { void load(); }, [load, workspace.id]);

  const activeInvitations = useMemo(
    () => invitations.filter((item) => item.status !== 'accepted'),
    [invitations],
  );

  function openEdit(member: WorkspaceMember) {
    setEditing(member);
    setEditDraft({
      role: member.role,
      allAgentsAccess: member.allAgentsAccess,
      agentIds: member.agentIds,
    });
  }

  async function submitInvitation(event: FormEvent) {
    event.preventDefault();
    const email = inviteDraft.email.trim().toLowerCase();
    if (!/^\S+@\S+\.\S+$/.test(email)) {
      pushToast('Enter a valid email address', 'error');
      return;
    }
    if (!inviteDraft.allAgentsAccess && agents.length > 0 && inviteDraft.agentIds.length === 0) {
      pushToast('Select at least one agent or enable all-agent access', 'error');
      return;
    }
    setSubmitting(true);
    try {
      const invitation = await workspaceTeamApi.invite({ ...inviteDraft, email });
      setInvitations((current) => [
        invitation,
        ...current.filter((item) => item.id !== invitation.id),
      ]);
      setInviteDraft(emptyDraft);
      setInviteOpen(false);
      pushToast(`Invitation sent to ${email}`);
    } catch (reason) {
      pushToast(reason instanceof Error ? reason.message : 'Invitation could not be sent', 'error');
    } finally {
      setSubmitting(false);
    }
  }

  async function saveMember(event: FormEvent) {
    event.preventDefault();
    if (!editing) return;
    if (!editDraft.allAgentsAccess && agents.length > 0 && editDraft.agentIds.length === 0) {
      pushToast('Select at least one agent or enable all-agent access', 'error');
      return;
    }
    setSubmitting(true);
    try {
      const updated = await workspaceTeamApi.updateMember(editing.userId, editDraft);
      setMembers((current) => current.map((member) => (
        member.userId === updated.userId ? updated : member
      )));
      setEditing(null);
      pushToast(`${updated.name}'s access was updated`);
    } catch (reason) {
      pushToast(reason instanceof Error ? reason.message : 'Member access could not be updated', 'error');
    } finally {
      setSubmitting(false);
    }
  }

  async function remove(member: WorkspaceMember) {
    if (!window.confirm(`Remove ${member.name} from ${workspace.name}?`)) return;
    setOperationId(member.userId);
    try {
      await workspaceTeamApi.removeMember(member.userId);
      setMembers((current) => current.filter((item) => item.userId !== member.userId));
      pushToast(`${member.name} was removed from the workspace`);
    } catch (reason) {
      pushToast(reason instanceof Error ? reason.message : 'Member could not be removed', 'error');
    } finally {
      setOperationId('');
    }
  }

  async function resend(invitation: WorkspaceInvitation) {
    setOperationId(invitation.id);
    try {
      const updated = await workspaceTeamApi.resendInvitation(invitation.id);
      setInvitations((current) => current.map((item) => (
        item.id === updated.id ? updated : item
      )));
      pushToast(`Invitation resent to ${updated.email}`);
    } catch (reason) {
      pushToast(reason instanceof Error ? reason.message : 'Invitation could not be resent', 'error');
    } finally {
      setOperationId('');
    }
  }

  async function revoke(invitation: WorkspaceInvitation) {
    if (!window.confirm(`Revoke the invitation for ${invitation.email}?`)) return;
    setOperationId(invitation.id);
    try {
      await workspaceTeamApi.revokeInvitation(invitation.id);
      setInvitations((current) => current.map((item) => (
        item.id === invitation.id ? { ...item, status: 'revoked' } : item
      )));
      pushToast(`Invitation for ${invitation.email} was revoked`);
    } catch (reason) {
      pushToast(reason instanceof Error ? reason.message : 'Invitation could not be revoked', 'error');
    } finally {
      setOperationId('');
    }
  }

  return <>
    <Card className="workspace-panel">
      <div className="workspace-panel__heading">
        <span><UsersRound /></span>
        <div><h3>Team members</h3><p>Invite teammates and enforce workspace, role, and agent-level access.</p></div>
        {canManage ? <Button icon={UserPlus} onClick={() => setInviteOpen(true)}>Invite member</Button> : null}
      </div>
      {loading ? <div className="workspace-team-state"><div><span className="workspace-invitation__spinner" /><h4>Loading team access</h4></div></div> : loadError ? <div className="workspace-team-state"><div><CircleAlert /><h4>Team access unavailable</h4><p>{loadError}</p>{canView ? <Button variant="secondary" icon={RefreshCw} onClick={() => void load()}>Try again</Button> : null}</div></div> : <>
        <section className="workspace-team-section">
          <div className="workspace-team-section__heading"><span><UsersRound /><strong>Active members</strong></span><small>{members.length} member{members.length === 1 ? '' : 's'}</small></div>
          <div className="workspace-member-list">
            {members.map((member) => <div key={member.userId}>
              <span className="mini-avatar">{member.name.charAt(0).toUpperCase()}</span>
              <span><strong>{member.name}{member.isSelf ? ' (you)' : ''}</strong><small>{member.email} · {member.allAgentsAccess ? 'All agents' : `${member.agentIds.length} selected agent${member.agentIds.length === 1 ? '' : 's'}`}</small></span>
              <Badge tone="success">Active</Badge>
              <Badge tone={member.role === 'workspace_admin' ? 'purple' : 'neutral'}>{roleLabel(member.role)}</Badge>
              {canManage && !member.isSelf ? <span className="workspace-member-list__actions">
                <Button size="sm" variant="ghost" icon={Pencil} onClick={() => openEdit(member)}>Edit</Button>
                <button type="button" className="icon-button danger-hover" disabled={operationId === member.userId} onClick={() => void remove(member)} aria-label={`Remove ${member.name}`}><Trash2 /></button>
              </span> : null}
            </div>)}
          </div>
        </section>
        <section className="workspace-team-section">
          <div className="workspace-team-section__heading"><span><Mail /><strong>Invitations</strong></span><small>{activeInvitations.length} record{activeInvitations.length === 1 ? '' : 's'}</small></div>
          {activeInvitations.length ? <div className="workspace-member-list">
            {activeInvitations.map((invitation) => <div key={invitation.id}>
              <span className="mini-avatar">{invitation.email.charAt(0).toUpperCase()}</span>
              <span><strong>{invitation.email}</strong><small>{invitation.allAgentsAccess ? 'All agents' : `${invitation.agentIds.length} selected agent${invitation.agentIds.length === 1 ? '' : 's'}`} · {invitation.deliveryState === 'failed' ? 'Delivery failed' : invitation.lastSentAt ? `Sent ${new Date(invitation.lastSentAt).toLocaleString()}` : 'Not sent'}</small></span>
              <span className="workspace-invitation-expiry"><Clock3 /> {new Date(invitation.expiresAt).toLocaleDateString()}</span>
              <Badge tone={invitationTone(invitation.status)}>{invitation.status}</Badge>
              <Badge tone="neutral">{roleLabel(invitation.role)}</Badge>
              {canManage && (invitation.status === 'pending' || invitation.status === 'expired') ? <span className="workspace-member-list__actions">
                <Button size="sm" variant="ghost" icon={RefreshCw} disabled={operationId === invitation.id} onClick={() => void resend(invitation)}>Resend</Button>
                <button type="button" className="icon-button danger-hover" disabled={operationId === invitation.id} onClick={() => void revoke(invitation)} aria-label={`Revoke invitation for ${invitation.email}`}><Trash2 /></button>
              </span> : null}
            </div>)}
          </div> : <div className="workspace-team-state"><div><Mail /><h4>No invitations</h4><p>Pending and historical invitation states will appear here.</p></div></div>}
        </section>
      </>}
    </Card>

    <Modal open={inviteOpen} onClose={() => !submitting && setInviteOpen(false)} title="Invite a team member" description="A secure, expiring, one-time link will be emailed to this address." closeDisabled={submitting} footer={<><Button variant="secondary" disabled={submitting} onClick={() => setInviteOpen(false)}>Cancel</Button><Button type="submit" form="workspace-team-invite-form" disabled={submitting}>{submitting ? 'Sending…' : 'Send invitation'}</Button></>}>
      <form id="workspace-team-invite-form" className="workspace-access-form" onSubmit={(event) => void submitInvitation(event)}>
        <Field label="Email address" htmlFor="invite-email"><input id="invite-email" type="email" value={inviteDraft.email} onChange={(event) => setInviteDraft((current) => ({ ...current, email: event.target.value }))} placeholder="name@company.com" autoComplete="email" autoFocus /></Field>
        <Field label="Workspace role" htmlFor="invite-role"><select id="invite-role" value={inviteDraft.role} onChange={(event) => setInviteDraft((current) => ({ ...current, role: event.target.value as WorkspaceRole }))}>{ROLE_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></Field>
        <div className="workspace-access-note"><ShieldCheck /><span>The invitee is not added until they explicitly accept with the invited email address. Existing accounts must sign in first.</span></div>
        <AccessScope draft={inviteDraft} onChange={(value) => setInviteDraft((current) => ({ ...current, ...value }))} agents={agents} />
      </form>
    </Modal>

    <Modal open={editing !== null} onClose={() => !submitting && setEditing(null)} title="Edit member access" description={editing ? `Update role and agent visibility for ${editing.email}.` : undefined} closeDisabled={submitting} footer={<><Button variant="secondary" disabled={submitting} onClick={() => setEditing(null)}>Cancel</Button><Button type="submit" form="workspace-member-edit-form" disabled={submitting}>{submitting ? 'Saving…' : 'Save access'}</Button></>}>
      <form id="workspace-member-edit-form" className="workspace-access-form" onSubmit={(event) => void saveMember(event)}>
        <Field label="Workspace role" htmlFor="member-role"><select id="member-role" value={editDraft.role} onChange={(event) => setEditDraft((current) => ({ ...current, role: event.target.value as WorkspaceRole }))}>{ROLE_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></Field>
        <AccessScope draft={editDraft} onChange={setEditDraft} agents={agents} />
      </form>
    </Modal>
  </>;
}

function AccessScope({ draft, onChange, agents }: {
  draft: WorkspaceAccessInput;
  onChange: (value: WorkspaceAccessInput) => void;
  agents: Agent[];
}) {
  function toggleAgent(agentId: string) {
    const selected = draft.agentIds.includes(agentId)
      ? draft.agentIds.filter((id) => id !== agentId)
      : [...draft.agentIds, agentId];
    onChange({ ...draft, agentIds: selected });
  }
  return <>
    <Switch checked={draft.allAgentsAccess} onChange={(checked) => onChange({ ...draft, allAgentsAccess: checked, agentIds: checked ? [] : draft.agentIds })} label="Access all agents" description="Disable this to restrict the member to selected agents only." />
    {!draft.allAgentsAccess ? <div className="workspace-agent-scope"><strong>Allowed agents</strong><small>The backend enforces this selection for agent-scoped operations.</small>{agents.length ? <div className="workspace-agent-scope__list">{agents.map((agent) => <label key={agent.id}><input type="checkbox" checked={draft.agentIds.includes(agent.id)} onChange={() => toggleAgent(agent.id)} /><span>{agent.name}</span></label>)}</div> : <div className="workspace-agent-scope__empty">No agents are available in this workspace yet.</div>}</div> : null}
  </>;
}
