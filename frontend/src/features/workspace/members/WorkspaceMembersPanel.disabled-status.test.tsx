/* @vitest-environment jsdom */
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { WorkspaceMembersPanel } from '@/features/workspace/members/WorkspaceMembersPanel';
import { workspaceTeamApi } from '@/lib/workspace-team-api';
import type { WorkspaceSettings } from '@/lib/workspace-api';

vi.mock('@/components/WorkspaceTeamPanel', () => ({ WorkspaceTeamPanel: () => <div>Existing team controls</div> }));
vi.mock('@/lib/workspace-api', () => ({ workspacePresentationKey: () => 'test-scope' }));
vi.mock('@/lib/workspace-team-api', () => ({
  workspaceTeamApi: {
    listMembers: vi.fn(), listMemberLifecycle: vi.fn(), listMemberDetails: vi.fn(),
    suspendMember: vi.fn(), reactivateMember: vi.fn(), removeMember: vi.fn(),
  },
}));

afterEach(() => { cleanup(); vi.resetAllMocks(); });
const workspace = {
  id: 'workspace-one', name: 'Workspace One',
  permissions: ['members.view', 'members.manage'],
} as WorkspaceSettings;
const member = {
  userId: 'disabled-user', name: 'Disabled member', email: 'disabled@example.com',
  role: 'viewer' as const, allAgentsAccess: true, agentIds: [],
  joinedAt: '2026-01-01T00:00:00Z', isSelf: false,
};

it('shows disabled as disabled and never offers the workspace-only Reactivate action', async () => {
  // Defensive check even when a legacy member list includes a disabled account.
  vi.mocked(workspaceTeamApi.listMembers).mockResolvedValue([member]);
  vi.mocked(workspaceTeamApi.listMemberLifecycle).mockResolvedValue([
    { userId: member.userId, status: 'disabled' },
  ]);
  vi.mocked(workspaceTeamApi.listMemberDetails).mockResolvedValue([]);
  render(<WorkspaceMembersPanel workspace={workspace} />);
  expect(await screen.findByText('disabled')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Reactivate' })).toBeNull();
  expect(screen.queryByRole('button', { name: 'Suspend' })).toBeNull();
  expect(workspaceTeamApi.reactivateMember).not.toHaveBeenCalled();
});

it('retains Reactivate for a workspace-suspended active account', async () => {
  vi.mocked(workspaceTeamApi.listMembers).mockResolvedValue([member]);
  vi.mocked(workspaceTeamApi.listMemberLifecycle).mockResolvedValue([
    { userId: member.userId, status: 'suspended' },
  ]);
  vi.mocked(workspaceTeamApi.listMemberDetails).mockResolvedValue([]);
  render(<WorkspaceMembersPanel workspace={workspace} />);
  expect(await screen.findByRole('button', { name: 'Reactivate' })).toBeTruthy();
});

it('shows a disabled member omitted by the legacy active-account-only endpoint', async () => {
  vi.mocked(workspaceTeamApi.listMembers).mockResolvedValue([]);
  vi.mocked(workspaceTeamApi.listMemberLifecycle).mockResolvedValue([
    { userId: member.userId, status: 'disabled' },
  ]);
  vi.mocked(workspaceTeamApi.listMemberDetails).mockResolvedValue([{
    userId: member.userId, name: member.name, email: member.email,
    role: member.role, status: 'disabled', mfaEnabled: false,
    lastLoginAt: null, invitedByUserId: null, joinedAt: member.joinedAt,
  }]);
  render(<WorkspaceMembersPanel workspace={workspace} />);
  expect((await screen.findAllByText('Disabled member')).length).toBeGreaterThanOrEqual(2);
  expect((await screen.findAllByText('disabled')).length).toBeGreaterThanOrEqual(2);
  expect(screen.queryByRole('button', { name: 'Reactivate' })).toBeNull();
  expect(screen.queryByRole('button', { name: 'Suspend' })).toBeNull();
});
