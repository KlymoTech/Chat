/* @vitest-environment jsdom */
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { WorkspaceMembersPanel } from '@/features/workspace/members/WorkspaceMembersPanel';
import { workspaceTeamApi } from '@/lib/workspace-team-api';
import type { WorkspaceSettings } from '@/lib/workspace-api';

vi.mock('@/components/WorkspaceTeamPanel', () => ({ WorkspaceTeamPanel: () => <div>Existing team controls</div> }));
vi.mock('@/features/workspace/members/WorkspaceMemberDetailsPanel', () => ({
  WorkspaceMemberDetailsPanel: () => <div>Member details mounted</div>,
}));
vi.mock('@/lib/workspace-api', () => ({ workspacePresentationKey: () => 'permission-scope' }));
vi.mock('@/lib/workspace-team-api', () => ({
  workspaceTeamApi: {
    listMembers: vi.fn(), listMemberLifecycle: vi.fn(), listMemberDetails: vi.fn(),
    suspendMember: vi.fn(), reactivateMember: vi.fn(),
  },
}));

const member = {
  userId: 'member-1', name: 'Example Member', email: 'member@example.test',
  role: 'operator' as const, allAgentsAccess: true, agentIds: [],
  joinedAt: '2026-09-21T00:00:00Z', isSelf: false,
};
function workspace(permissions: string[]): WorkspaceSettings {
  return { id: 'workspace-1', name: 'Workspace One', permissions } as WorkspaceSettings;
}

afterEach(() => { cleanup(); vi.resetAllMocks(); });

it('preserves legacy controls but does not mount additive readers without members.view', () => {
  render(<WorkspaceMembersPanel workspace={workspace(['members.manage'])} />);
  expect(screen.getByText('Existing team controls')).toBeTruthy();
  expect(screen.queryByText('Member details mounted')).toBeNull();
  expect(screen.queryByText('Member lifecycle')).toBeNull();
  expect(workspaceTeamApi.listMembers).not.toHaveBeenCalled();
  expect(workspaceTeamApi.listMemberLifecycle).not.toHaveBeenCalled();
  expect(workspaceTeamApi.listMemberDetails).not.toHaveBeenCalled();
});

it('does not assume a missing lifecycle record is active or permit a suspension', async () => {
  vi.mocked(workspaceTeamApi.listMembers).mockResolvedValue([member]);
  vi.mocked(workspaceTeamApi.listMemberLifecycle).mockResolvedValue([]);
  render(<WorkspaceMembersPanel workspace={workspace(['members.view', 'members.manage'])} />);
  expect(await screen.findByText('Example Member')).toBeTruthy();
  expect(screen.getByText('Unavailable')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Suspend' })).toBeNull();
  expect(screen.queryByRole('button', { name: 'Reactivate' })).toBeNull();
  await waitFor(() => expect(workspaceTeamApi.listMemberLifecycle).toHaveBeenCalledTimes(1));
});
