import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { Button, Card, Field, Modal } from '@/components/ui';
import { emitWorkspaceMemberChanged, onWorkspaceMemberChanged } from '@/features/workspace/members/workspaceMemberEvents';
import { workspaceTeamApi, type WorkspaceMemberDetails } from '@/lib/workspace-team-api';

/** Workspace-scoped member metadata; existing invite/access controls remain untouched. */
export function WorkspaceMemberDetailsPanel({ canManage = false }: { canManage?: boolean }) {
  const [members, setMembers] = useState<WorkspaceMemberDetails[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [target, setTarget] = useState<WorkspaceMemberDetails | null>(null);
  const [confirmation, setConfirmation] = useState('');
  const [removalError, setRemovalError] = useState('');
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setLoading(true);
    setError('');
    try {
      const next = await workspaceTeamApi.listMemberDetails(request.signal);
      if (!request.signal.aborted) setMembers(next);
    } catch (cause) {
      if (!request.signal.aborted) {
        setMembers([]);
        setError(cause instanceof Error ? cause.message : 'Member details could not be loaded');
      }
    } finally {
      if (!request.signal.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const unsubscribe = onWorkspaceMemberChanged(() => { void load(); });
    return () => { unsubscribe(); controller.current?.abort(); };
  }, [load]);

  function openRemoval(member: WorkspaceMemberDetails) {
    if (!canManage || member.status !== 'disabled' || busy) return;
    setTarget(member);
    setConfirmation('');
    setRemovalError('');
  }

  async function submitRemoval(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canManage || !target || target.status !== 'disabled' || confirmation !== 'REMOVE' || busy) return;
    setBusy(true);
    setRemovalError('');
    try {
      // The existing permission-protected API enforces owner and last-admin guards.
      await workspaceTeamApi.removeMember(target.userId);
      setTarget(null);
      setConfirmation('');
      emitWorkspaceMemberChanged('member-removed');
    } catch (cause) {
      setRemovalError(cause instanceof Error ? cause.message : 'Member could not be removed');
    } finally {
      setBusy(false);
    }
  }

  const names = new Map(members.map((member) => [member.userId, member.name]));
  const date = (value: string | null) => {
    if (!value) return 'Not recorded';
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? 'Not recorded' : parsed.toLocaleString();
  };
  return <>
    <Card className="workspace-panel">
      <div className="workspace-panel__heading"><div><h3>Member details</h3>
        <p>Last sign-in is account-wide, not activity measured within this workspace. Team assignments will appear when team membership is implemented.</p>
      </div></div>
      <div className="workspace-panel__body">
        {loading ? <p role="status">Loading member details…</p> : null}
        {error ? <div role="alert"><p>{error}</p><Button type="button" onClick={() => void load()}>Retry member details</Button></div> : null}
        {!loading && !error && members.length === 0 ? <p>No workspace members found.</p> : null}
        {!loading && !error && members.length > 0 ? <>
          <Button type="button" variant="secondary" onClick={() => void load()}>Refresh member details</Button>
          <div style={{ overflowX: 'auto' }}>
            <table className="workspace-member-details-table">
              <thead><tr><th scope="col">Name / email</th><th scope="col">Role</th>
                <th scope="col">Status</th><th scope="col">MFA</th>
                <th scope="col">Account last sign-in</th><th scope="col">Invited by</th>
                <th scope="col">Joined</th>{canManage ? <th scope="col">Actions</th> : null}</tr></thead>
              <tbody>{members.map((member) => <tr key={member.userId}>
                <td><strong>{member.name}</strong><br />{member.email}</td>
                <td>{member.role.replaceAll('_', ' ')}</td><td>{member.status}</td>
                <td>{member.mfaEnabled ? 'Enabled' : 'Not enabled'}</td>
                <td>{date(member.lastLoginAt)}</td>
                <td>{member.invitedByUserId ? names.get(member.invitedByUserId) ?? 'Inviter no longer in workspace' : 'Not recorded'}</td>
                <td>{date(member.joinedAt)}</td>
                {canManage ? <td>{member.status === 'disabled'
                  ? <Button type="button" size="sm" variant="danger" disabled={busy} onClick={() => openRemoval(member)}>Remove disabled member</Button>
                  : null}</td> : null}
              </tr>)}</tbody>
            </table>
          </div>
        </> : null}
      </div>
    </Card>
    <Modal open={target !== null} onClose={() => { if (!busy) setTarget(null); }} closeDisabled={busy}
      title="Remove disabled workspace member"
      description={target ? `${target.name} (${target.email}). This removes their membership only in the selected workspace; it does not delete their account.` : undefined}
      footer={<>
        <Button type="button" variant="secondary" disabled={busy} onClick={() => setTarget(null)}>Cancel</Button>
        <Button type="submit" form="workspace-disabled-member-remove-form" variant="danger" disabled={busy || confirmation !== 'REMOVE'}>{busy ? 'Removing…' : 'Remove member'}</Button>
      </>}>
      {removalError ? <p role="alert">{removalError}</p> : null}
      <form id="workspace-disabled-member-remove-form" onSubmit={(event) => void submitRemoval(event)}>
        <Field label="Type REMOVE to confirm"><input required autoComplete="off" value={confirmation} disabled={busy} onChange={(event) => setConfirmation(event.target.value)} /></Field>
      </form>
    </Modal>
  </>;
}
