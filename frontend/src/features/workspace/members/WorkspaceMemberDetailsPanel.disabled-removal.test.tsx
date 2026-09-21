/* @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { WorkspaceMemberDetailsPanel } from '@/features/workspace/members/WorkspaceMemberDetailsPanel';
import { workspaceTeamApi } from '@/lib/workspace-team-api';

vi.mock('@/lib/workspace-team-api', () => ({
  workspaceTeamApi: { listMemberDetails: vi.fn(), removeMember: vi.fn() },
}));

afterEach(() => { cleanup(); vi.resetAllMocks(); });

const disabledMember = {
  userId: 'disabled-user-id', name: 'Disabled Employee', email: 'disabled@example.com',
  role: 'viewer' as const, status: 'disabled' as const, mfaEnabled: false,
  lastLoginAt: null, invitedByUserId: null, joinedAt: '2026-09-01T00:00:00Z',
};

it('does not expose a removal action to a member without members.manage', async () => {
  vi.mocked(workspaceTeamApi.listMemberDetails).mockResolvedValue([disabledMember]);
  render(<WorkspaceMemberDetailsPanel canManage={false} />);
  expect(await screen.findByText('Disabled Employee')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Remove disabled member' })).toBeNull();
  expect(workspaceTeamApi.removeMember).not.toHaveBeenCalled();
});

it('limits cleanup actions to disabled members and requires typed confirmation', async () => {
  vi.mocked(workspaceTeamApi.listMemberDetails).mockResolvedValue([
    disabledMember,
    { ...disabledMember, userId: 'active-user', name: 'Active Employee', status: 'active' },
  ]);
  render(<WorkspaceMemberDetailsPanel canManage />);
  expect(await screen.findByText('Active Employee')).toBeTruthy();
  expect(screen.getAllByRole('button', { name: 'Remove disabled member' })).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: 'Remove disabled member' }));
  const submit = screen.getByRole('button', { name: 'Remove member' });
  expect(submit).toHaveProperty('disabled', true);
  fireEvent.change(screen.getByLabelText('Type REMOVE to confirm'), { target: { value: 'remove' } });
  expect(submit).toHaveProperty('disabled', true);
  expect(workspaceTeamApi.removeMember).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(workspaceTeamApi.removeMember).not.toHaveBeenCalled();
});

it('removes only the selected disabled membership and reloads authoritative details', async () => {
  vi.mocked(workspaceTeamApi.listMemberDetails)
    .mockResolvedValueOnce([disabledMember])
    .mockResolvedValueOnce([]);
  vi.mocked(workspaceTeamApi.removeMember).mockResolvedValue(undefined);
  render(<WorkspaceMemberDetailsPanel canManage />);
  expect(await screen.findByText('Disabled Employee')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Remove disabled member' }));
  fireEvent.change(screen.getByLabelText('Type REMOVE to confirm'), { target: { value: 'REMOVE' } });
  fireEvent.click(screen.getByRole('button', { name: 'Remove member' }));
  await waitFor(() => expect(workspaceTeamApi.removeMember).toHaveBeenCalledExactlyOnceWith('disabled-user-id'));
  expect(await screen.findByText('No workspace members found.')).toBeTruthy();
});

it('keeps the confirmation open with a visible API error when removal is rejected', async () => {
  vi.mocked(workspaceTeamApi.listMemberDetails).mockResolvedValue([disabledMember]);
  vi.mocked(workspaceTeamApi.removeMember).mockRejectedValue(new Error('Transfer ownership before removing this member'));
  render(<WorkspaceMemberDetailsPanel canManage />);
  expect(await screen.findByText('Disabled Employee')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Remove disabled member' }));
  fireEvent.change(screen.getByLabelText('Type REMOVE to confirm'), { target: { value: 'REMOVE' } });
  fireEvent.click(screen.getByRole('button', { name: 'Remove member' }));
  expect(await screen.findByRole('alert')).toHaveProperty('textContent', expect.stringContaining('Transfer ownership'));
  expect(screen.getByRole('button', { name: 'Remove member' })).toBeTruthy();
  expect(workspaceTeamApi.listMemberDetails).toHaveBeenCalledTimes(1);
});
