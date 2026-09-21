import { useEffect, useState, type FormEvent } from 'react';
import { Button, Card, Field } from '@/components/ui';
import {
  activeWorkspaceId, workspaceApi, workspacePresentationKey,
  type WorkspaceOwner, type WorkspaceOwnerTransfer, type WorkspaceTeamMember,
} from '@/lib/workspace-api';
import { workspaceTeamApi } from '@/lib/workspace-team-api';
import { WorkspaceOwnerRecoveryPanel } from './WorkspaceOwnerRecoveryPanel';

interface Props {
  workspaceId: string;
  currentUserId: string;
  canManage: boolean;
}

/** Separate form: ownership transfer must never be submitted by Save profile. */
export function WorkspaceOwnershipPanel({ workspaceId, currentUserId, canManage }: Props) {
  const [owner, setOwner] = useState<WorkspaceOwner | null>(null);
  const [admins, setAdmins] = useState<WorkspaceTeamMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [targetId, setTargetId] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [reason, setReason] = useState<WorkspaceOwnerTransfer['reason'] | ''>('');
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let live = true;
    const controller = new AbortController();
    const selectedId = activeWorkspaceId();
    const identity = workspacePresentationKey();
    const stillHere = () => live && selectedId === activeWorkspaceId() && identity === workspacePresentationKey();
    setOwner(null); setAdmins([]); setError(null); setNotice(null); setLoading(true);
    setTargetId(''); setConfirmation(''); setReason('');
    void workspaceApi.getOwner(controller.signal).then(async (result) => {
      if (!stillHere()) return;
      setOwner(result);
      if (canManage && result.ownerUserId === currentUserId) {
        const [team, lifecycle] = await Promise.all([
          workspaceApi.getTeam(), workspaceTeamApi.listMemberLifecycle(controller.signal),
        ]);
        if (!stillHere()) return;
        const suspendedIds = new Set(lifecycle.filter((item) => item.status === 'suspended').map((item) => item.userId));
        setAdmins(team.members.filter((member) => member.role === 'workspace_admin'
          && member.id !== result.ownerUserId && !suspendedIds.has(member.id)));
      }
    }).catch((cause: unknown) => {
      if (stillHere()) setError(cause instanceof Error ? cause.message : 'Workspace owner could not be loaded');
    }).finally(() => { if (stillHere()) setLoading(false); });
    return () => { live = false; controller.abort(); };
  }, [workspaceId, currentUserId, canManage, revision]);

  const mayTransfer = canManage && !!owner?.ownerUserId && owner.ownerUserId === currentUserId;
  async function transfer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!mayTransfer || !owner?.ownerUserId || !targetId || !reason || confirmation !== 'TRANSFER' || saving) return;
    const selectedId = activeWorkspaceId();
    const identity = workspacePresentationKey();
    const stillHere = () => selectedId === activeWorkspaceId() && identity === workspacePresentationKey();
    setSaving(true); setError(null); setNotice(null);
    try {
      const next = await workspaceApi.transferOwner({
        expectedOwnerUserId: owner.ownerUserId,
        targetUserId: targetId,
        reason,
        confirmation: 'TRANSFER',
      });
      if (stillHere()) {
        setOwner(next); setAdmins([]); setTargetId(''); setConfirmation(''); setReason('');
        setNotice('Workspace ownership transferred. Your administrator access is unchanged.');
      }
    } catch (cause) {
      if (stillHere()) setError(cause instanceof Error ? cause.message : 'Ownership transfer could not be completed');
    } finally { if (stillHere()) setSaving(false); }
  }

  return <Card className="workspace-panel">
    <div className="workspace-panel__heading"><div><h3>Workspace owner</h3><p>Ownership is separate from the workspace creator and administrator role.</p></div></div>
    <div className="workspace-panel__body">
      {loading ? <p role="status">Loading workspace owner…</p> : owner?.ownerUserId
        ? <p><strong>{owner.ownerName ?? 'Workspace administrator'}</strong> <span>({owner.ownerUserId})</span></p>
        : <p role="status">No active workspace owner is available. Contact your organization administrator to recover ownership.</p>}
      {error ? <p role="alert">{error}</p> : null}
      {notice ? <p role="status">{notice}</p> : null}
      {error && !saving ? <Button type="button" onClick={() => setRevision((value) => value + 1)}>Retry loading owner</Button> : null}
      {mayTransfer && !error ? <details>
        <summary>Transfer workspace ownership</summary>
        <p>Choose an existing active workspace administrator. The original creator record and both administrators' roles remain unchanged.</p>
        {admins.length ? <form onSubmit={(event) => void transfer(event)}>
          <Field label="New workspace owner"><select value={targetId} required disabled={saving} onChange={(event) => setTargetId(event.target.value)}>
            <option value="">Select an administrator</option>
            {admins.map((member) => <option key={member.id} value={member.id}>{member.name} ({member.email})</option>)}
          </select></Field>
          <Field label="Transfer reason"><select value={reason} required disabled={saving} onChange={(event) => setReason(event.target.value as WorkspaceOwnerTransfer['reason'] | '')}>
            <option value="">Choose a reason</option>
            <option value="administrative_handover">Administrative handover</option>
            <option value="responsibility_change">Responsibility change</option>
            <option value="account_recovery">Account recovery</option>
          </select></Field>
          <Field label="Type TRANSFER to confirm"><input value={confirmation} required disabled={saving} autoComplete="off" onChange={(event) => setConfirmation(event.target.value)} /></Field>
          <Button type="submit" disabled={saving || !targetId || !reason || confirmation !== 'TRANSFER'}>
            {saving ? 'Transferring…' : 'Confirm ownership transfer'}
          </Button>
        </form> : <p>Invite or promote another active workspace administrator before transferring ownership.</p>}
      </details> : null}
      {owner && !owner.ownerUserId && !error ? <WorkspaceOwnerRecoveryPanel
        workspaceId={workspaceId} currentUserId={currentUserId} canManage={canManage}
        onRecovered={(next) => { setOwner(next); setNotice('Workspace ownership recovered and audited.'); }}
      /> : null}
    </div>
  </Card>;
}
