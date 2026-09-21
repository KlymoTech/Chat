/* @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { WorkspaceMemberDetailsPanel } from '@/features/workspace/members/WorkspaceMemberDetailsPanel';
import { emitWorkspaceMemberChanged } from '@/features/workspace/members/workspaceMemberEvents';
import { workspaceTeamApi } from '@/lib/workspace-team-api';

vi.mock('@/lib/workspace-team-api', () => ({
  workspaceTeamApi: { listMemberDetails: vi.fn() },
}));

afterEach(() => { cleanup(); vi.resetAllMocks(); });

it('labels account-wide sign-in explicitly and renders authoritative member metadata', async () => {
  vi.mocked(workspaceTeamApi.listMemberDetails).mockResolvedValue([{
    userId: 'inviter', name: 'Inviting Admin', email: 'admin@example.com', role: 'workspace_admin',
    status: 'active', mfaEnabled: true, lastLoginAt: '2026-09-20T10:00:00Z',
    invitedByUserId: null, joinedAt: '2026-09-01T00:00:00Z',
  }, {
    userId: 'invitee', name: 'Invited Member', email: 'member@example.com', role: 'operator',
    status: 'suspended', mfaEnabled: false, lastLoginAt: null,
    invitedByUserId: 'inviter', joinedAt: '2026-09-02T00:00:00Z',
  }]);
  render(<WorkspaceMemberDetailsPanel />);
  expect(await screen.findByText('Invited Member')).toBeTruthy();
  expect(screen.getByRole('columnheader', { name: 'Account last sign-in' })).toBeTruthy();
  expect(screen.getByText(/not activity measured within this workspace/i)).toBeTruthy();
  expect(screen.getByText('suspended')).toBeTruthy();
  expect(screen.getByText('Not enabled')).toBeTruthy();
  expect(screen.getAllByText('Inviting Admin').length).toBeGreaterThan(0);
});

it('shows a retryable error then loads without retaining previous workspace data', async () => {
  vi.mocked(workspaceTeamApi.listMemberDetails)
    .mockRejectedValueOnce(new Error('Member details unavailable'))
    .mockResolvedValueOnce([]);
  render(<WorkspaceMemberDetailsPanel />);
  expect(await screen.findByRole('alert')).toHaveProperty('textContent', expect.stringContaining('Member details unavailable'));
  fireEvent.click(screen.getByRole('button', { name: 'Retry member details' }));
  await waitFor(() => expect(workspaceTeamApi.listMemberDetails).toHaveBeenCalledTimes(2));
  expect(await screen.findByText('No workspace members found.')).toBeTruthy();
  expect(screen.queryByRole('alert')).toBeNull();
});

it('refreshes authoritative details after a workspace member mutation event', async () => {
  vi.mocked(workspaceTeamApi.listMemberDetails)
    .mockResolvedValueOnce([{
      userId: 'member', name: 'Member', email: 'member@example.com', role: 'viewer',
      status: 'active', mfaEnabled: false, lastLoginAt: null,
      invitedByUserId: null, joinedAt: '2026-09-02T00:00:00Z',
    }])
    .mockResolvedValueOnce([{
      userId: 'member', name: 'Member', email: 'member@example.com', role: 'manager',
      status: 'active', mfaEnabled: false, lastLoginAt: null,
      invitedByUserId: null, joinedAt: '2026-09-02T00:00:00Z',
    }]);
  render(<WorkspaceMemberDetailsPanel />);
  expect(await screen.findByText('viewer')).toBeTruthy();
  emitWorkspaceMemberChanged('member-updated');
  await waitFor(() => expect(workspaceTeamApi.listMemberDetails).toHaveBeenCalledTimes(2));
  expect(await screen.findByText('manager')).toBeTruthy();
  expect(screen.queryByText('viewer')).toBeNull();
});
