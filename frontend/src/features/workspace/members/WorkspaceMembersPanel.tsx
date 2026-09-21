import { PauseCircle, PlayCircle, UsersRound } from 'lucide-react';
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { WorkspaceTeamPanel } from '@/components/WorkspaceTeamPanel';
import { Badge, Button, Card, Field, Modal } from '@/components/ui';
import {
  workspaceTeamApi,
  type WorkspaceMember,
  type WorkspaceMemberLifecycle,
} from '@/lib/workspace-team-api';
import { workspacePresentationKey, type WorkspaceSettings } from '@/lib/workspace-api';

/**
 * Incremental migration wrapper. Existing invitation/role/resource-scope behavior
 * remains in WorkspaceTeamPanel while member lifecycle state is owned here.
 */
export function WorkspaceMembersPanel({ workspace }: { workspace: WorkspaceSettings }) {
  const context = `${workspacePresentationKey()}:${workspace.id}:${[...(workspace.permissions ?? [])].sort().join(',')}`;
  return <div key={context}>
    <WorkspaceTeamPanel workspace={workspace} />
    <WorkspaceMemberLifecyclePanel workspace={workspace} />
  </div>;
}

function WorkspaceMemberLifecyclePanel({ workspace }: { workspace: WorkspaceSettings }) {
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [states, setStates] = useState<Record<string, WorkspaceMemberLifecycle['status']>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [target, setTarget] = useState<WorkspaceMember | null>(null);
  const [nextStatus, setNextStatus] = useState<WorkspaceMemberLifecycle['status']>('suspended');
  const [reason, setReason] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const controller = useRef<AbortController | null>(null);
  const canManage = workspace.permissions?.includes('members.manage') ?? false;

  const load = useCallback(async () => {
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setLoading(true); setError('');
    try {
      const [nextMembers, lifecycle] = await Promise.all([
        workspaceTeamApi.listMembers(request.signal),
        workspaceTeamApi.listMemberLifecycle(request.signal),
      ]);
      if (request.signal.aborted) return;
      setMembers(nextMembers);
      setStates(Object.fromEntries(lifecycle.map((item) => [item.userId, item.status])));
    } catch (cause) {
      if (!request.signal.aborted) setError(cause instanceof Error ? cause.message : 'Member lifecycle could not be loaded');
    } finally { if (!request.signal.aborted) setLoading(false); }
  }, []);

  useEffect(() => { void load(); return () => controller.current?.abort(); }, [load]);

  function open(member: WorkspaceMember, status: WorkspaceMemberLifecycle['status']) {
    setTarget(member); setNextStatus(status); setReason(''); setConfirmation(''); setError('');
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!target || !canManage || busy) return;
    const expected = nextStatus === 'suspended' ? 'SUSPEND' : 'REACTIVATE';
    if (confirmation !== expected) return;
    setBusy(true); setError('');
    try {
      const result = nextStatus === 'suspended'
        ? await workspaceTeamApi.suspendMember(target.userId, reason)
        : await workspaceTeamApi.reactivateMember(target.userId, reason);
      setStates((old) => ({ ...old, [result.userId]: result.status }));
      setTarget(null); setReason(''); setConfirmation('');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Member lifecycle change could not be completed');
    } finally { setBusy(false); }
  }

  const expectedConfirmation = nextStatus === 'suspended' ? 'SUSPEND' : 'REACTIVATE';
  return <>
    <Card className="workspace-panel">
      <div className="workspace-panel__heading"><span><UsersRound /></span><div><h3>Member lifecycle</h3><p>Suspend or reactivate access for this workspace without disabling the global user account.</p></div></div>
      <div className="workspace-panel__body">
        {loading ? <p role="status">Loading member lifecycle…</p> : null}
        {error && !target ? <div role="alert"><p>{error}</p><Button type="button" onClick={() => void load()}>Retry</Button></div> : null}
        {!loading && !error && members.length === 0 ? <p>No workspace members are available.</p> : null}
        {!loading && members.length > 0 ? <div className="workspace-member-list">
          {members.map((member) => {
            const status = states[member.userId] ?? 'active';
            return <div key={member.userId}>
              <span className="mini-avatar">{member.name.charAt(0).toUpperCase()}</span>
              <span><strong>{member.name}{member.isSelf ? ' (you)' : ''}</strong><small>{member.email}</small></span>
              <Badge tone={status === 'active' ? 'success' : 'warning'}>{status}</Badge>
              {canManage && !member.isSelf ? <span className="workspace-member-list__actions">
                {status === 'active'
                  ? <Button size="sm" variant="ghost" icon={PauseCircle} onClick={() => open(member, 'suspended')}>Suspend</Button>
                  : <Button size="sm" variant="ghost" icon={PlayCircle} onClick={() => open(member, 'active')}>Reactivate</Button>}
              </span> : null}
            </div>;
          })}
        </div> : null}
      </div>
    </Card>
    <Modal open={target !== null} onClose={() => !busy && setTarget(null)} closeDisabled={busy}
      title={nextStatus === 'suspended' ? 'Suspend workspace member' : 'Reactivate workspace member'}
      description={target ? `${target.name} (${target.email}). This changes only access to ${workspace.name}.` : undefined}
      footer={<><Button variant="secondary" disabled={busy} onClick={() => setTarget(null)}>Cancel</Button><Button type="submit" form="workspace-member-lifecycle-form" variant={nextStatus === 'suspended' ? 'danger' : 'primary'} disabled={busy || reason.trim().length < 3 || confirmation !== expectedConfirmation}>{busy ? 'Saving…' : nextStatus === 'suspended' ? 'Suspend member' : 'Reactivate member'}</Button></>}>
      {error ? <p role="alert">{error}</p> : null}
      <form id="workspace-member-lifecycle-form" onSubmit={(event) => void submit(event)}>
        <Field label="Reason"><textarea required minLength={3} maxLength={500} value={reason} disabled={busy} onChange={(event) => setReason(event.target.value)} /></Field>
        <Field label={`Type ${expectedConfirmation} to confirm`}><input required autoComplete="off" value={confirmation} disabled={busy} onChange={(event) => setConfirmation(event.target.value)} /></Field>
      </form>
    </Modal>
  </>;
}
