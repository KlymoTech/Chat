import { useEffect, useState, type FormEvent } from 'react';
import { Button, Field } from '@/components/ui';
import { readStorage } from '@/lib/storage';
import { activeWorkspaceId, workspacePresentationKey, type WorkspaceOwner } from '@/lib/workspace-api';
import { workspaceTeamApi, type WorkspaceMemberDetails } from '@/lib/workspace-team-api';
import { recoverWorkspaceOwner, type WorkspaceRecoveryReason } from './workspaceOwnerRecovery.api';

interface Props {
  workspaceId: string;
  currentUserId: string;
  canManage: boolean;
  onRecovered: (owner: WorkspaceOwner) => void;
}

/** Visible only to organization owners; the backend independently verifies authority. */
export function WorkspaceOwnerRecoveryPanel({ workspaceId, currentUserId, canManage, onRecovered }: Props) {
  const isOrganizationOwner = readStorage<{ user?: { role?: string } } | null>('northstar.session', null)?.user?.role === 'owner';
  const available = canManage && isOrganizationOwner && workspaceId !== 'workspace-demo';
  const [admins, setAdmins] = useState<WorkspaceMemberDetails[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [targetId, setTargetId] = useState('');
  const [reason, setReason] = useState<WorkspaceRecoveryReason | ''>('');
  const [confirmation, setConfirmation] = useState('');
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    if (!available) return;
    let live = true;
    const controller = new AbortController();
    const selectedId = activeWorkspaceId();
    const identity = workspacePresentationKey();
    const stillHere = () => live && selectedId === activeWorkspaceId() && identity === workspacePresentationKey();
    setLoading(true); setError(null); setAdmins([]);
    void workspaceTeamApi.listMemberDetails(controller.signal).then((members) => {
      if (stillHere()) setAdmins(members.filter((member) => member.role === 'workspace_admin'
        && member.status === 'active' && member.userId !== currentUserId));
    }).catch((cause: unknown) => {
      if (stillHere()) setError(cause instanceof Error ? cause.message : 'Recovery candidates could not be loaded');
    }).finally(() => { if (stillHere()) setLoading(false); });
    return () => { live = false; controller.abort(); };
  }, [workspaceId, currentUserId, available, revision]);

  if (!available) return null;

  async function recover(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!targetId || !reason || confirmation !== 'RECOVER' || saving) return;
    const selectedId = activeWorkspaceId();
    const identity = workspacePresentationKey();
    const stillHere = () => selectedId === activeWorkspaceId() && identity === workspacePresentationKey();
    setSaving(true); setError(null);
    try {
      const result = await recoverWorkspaceOwner({ targetUserId: targetId, reason, confirmation: 'RECOVER' });
      if (stillHere()) onRecovered(result);
    } catch (cause) {
      if (stillHere()) setError(cause instanceof Error ? cause.message : 'Workspace ownership could not be recovered');
    } finally { if (stillHere()) setSaving(false); }
  }

  return <section aria-label="Organization owner recovery">
    <h4>Recover unavailable workspace ownership</h4>
    <p>Only the organization owner can appoint a different, active workspace administrator when no eligible owner remains. This is audited and cannot be used to replace an active owner.</p>
    {loading ? <p role="status">Loading recovery candidates…</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    {error && !saving ? <Button type="button" onClick={() => setRevision((value) => value + 1)}>Retry recovery candidates</Button> : null}
    {!loading && !error && !admins.length ? <p role="status">Invite or promote another active administrator before recovering ownership.</p> : null}
    {!loading && !error && admins.length ? <form onSubmit={(event) => void recover(event)}>
      <Field label="Recovery administrator"><select required value={targetId} disabled={saving} onChange={(event) => setTargetId(event.target.value)}>
        <option value="">Select an administrator</option>
        {admins.map((member) => <option key={member.userId} value={member.userId}>{member.name} ({member.email})</option>)}
      </select></Field>
      <Field label="Recovery reason"><select required value={reason} disabled={saving} onChange={(event) => setReason(event.target.value as WorkspaceRecoveryReason | '')}>
        <option value="">Choose a reason</option>
        <option value="recorded_owner_unavailable">Recorded owner is unavailable</option>
        <option value="legacy_owner_unavailable">Legacy workspace has no eligible owner</option>
      </select></Field>
      <Field label="Type RECOVER to confirm"><input value={confirmation} disabled={saving} required autoComplete="off" onChange={(event) => setConfirmation(event.target.value)} /></Field>
      <Button type="submit" disabled={saving || !targetId || !reason || confirmation !== 'RECOVER'}>
        {saving ? 'Recovering…' : 'Confirm ownership recovery'}
      </Button>
    </form> : null}
  </section>;
}
