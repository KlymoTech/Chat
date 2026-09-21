/* @vitest-environment jsdom */
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import { WorkspaceMembersPanel } from '@/features/workspace/members/WorkspaceMembersPanel';
import type { WorkspaceSettings } from '@/lib/workspace-api';

const mocks = vi.hoisted(() => ({
  listMembers: vi.fn(),
  listMemberLifecycle: vi.fn(),
  suspendMember: vi.fn(),
  reactivateMember: vi.fn(),
  emitWorkspaceMemberChanged: vi.fn(),
}));

vi.mock('@/components/WorkspaceTeamPanel', () => ({
  WorkspaceTeamPanel: () => <div>Existing team controls</div>,
}));
vi.mock('@/features/workspace/members/WorkspaceMemberDetailsPanel', () => ({
  WorkspaceMemberDetailsPanel: () => <div>Member details</div>,
}));
vi.mock('@/features/workspace/members/workspaceMemberEvents', () => ({
  emitWorkspaceMemberChanged: mocks.emitWorkspaceMemberChanged,
  onWorkspaceMemberChanged: () => () => undefined,
}));
vi.mock('@/lib/workspace-api', () => ({ workspacePresentationKey: () => 'test-scope' }));
vi.mock('@/lib/workspace-team-api', () => ({
  workspaceTeamApi: {
    listMembers: mocks.listMembers,
    listMemberLifecycle: mocks.listMemberLifecycle,
    suspendMember: mocks.suspendMember,
    reactivateMember: mocks.reactivateMember,
  },
}));

afterEach(() => { cleanup(); vi.resetAllMocks(); });

it('emits suspension, not reactivation, when global disablement overrides the result', async () => {
  const member = {
    userId: 'member-one', name: 'Workspace member', email: 'member@example.com',
    role: 'viewer', allAgentsAccess: true, agentIds: [],
    joinedAt: '2026-09-01T00:00:00Z', isSelf: false,
  };
  mocks.listMembers.mockResolvedValue([member]);
  mocks.listMemberLifecycle.mockResolvedValue([{ userId: member.userId, status: 'active' }]);
  mocks.suspendMember.mockResolvedValue({ userId: member.userId, status: 'disabled' });
  const workspace = {
    id: 'workspace-one', name: 'Workspace One',
    permissions: ['members.view', 'members.manage'],
  } as WorkspaceSettings;
  const user = userEvent.setup();
  render(<WorkspaceMembersPanel workspace={workspace} />);

  await user.click(await screen.findByRole('button', { name: 'Suspend' }));
  await user.type(screen.getByLabelText('Reason'), 'Access review');
  await user.type(screen.getByLabelText('Type SUSPEND to confirm'), 'SUSPEND');
  await user.click(screen.getByRole('button', { name: 'Suspend member' }));

  await waitFor(() => expect(mocks.suspendMember).toHaveBeenCalledWith('member-one', 'Access review'));
  await waitFor(() => expect(mocks.emitWorkspaceMemberChanged).toHaveBeenCalledWith('member-suspended'));
  expect(mocks.emitWorkspaceMemberChanged).not.toHaveBeenCalledWith('member-reactivated');
  expect(await screen.findByText('disabled')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Reactivate' })).not.toBeInTheDocument();
});
