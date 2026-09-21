import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Card } from '@/components/ui';
import { onWorkspaceMemberChanged } from '@/features/workspace/members/workspaceMemberEvents';
import { workspaceTeamApi, type WorkspaceMemberDetails } from '@/lib/workspace-team-api';

/** Read-only member metadata; existing invite/access controls remain untouched. */
export function WorkspaceMemberDetailsPanel() {
  const [members, setMembers] = useState<WorkspaceMemberDetails[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
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

  const names = new Map(members.map((member) => [member.userId, member.name]));
  const date = (value: string | null) => {
    if (!value) return 'Not recorded';
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? 'Not recorded' : parsed.toLocaleString();
  };
  return <Card className="workspace-panel">
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
              <th scope="col">Joined</th></tr></thead>
            <tbody>{members.map((member) => <tr key={member.userId}>
              <td><strong>{member.name}</strong><br />{member.email}</td>
              <td>{member.role.replaceAll('_', ' ')}</td><td>{member.status}</td>
              <td>{member.mfaEnabled ? 'Enabled' : 'Not enabled'}</td>
              <td>{date(member.lastLoginAt)}</td>
              <td>{member.invitedByUserId ? names.get(member.invitedByUserId) ?? 'Inviter no longer in workspace' : 'Not recorded'}</td>
              <td>{date(member.joinedAt)}</td>
            </tr>)}</tbody>
          </table>
        </div>
      </> : null}
    </div>
  </Card>;
}
