/* @vitest-environment jsdom */
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { WorkspaceMemberDetailsPanel } from '@/features/workspace/members/WorkspaceMemberDetailsPanel';
import { workspaceTeamApi } from '@/lib/workspace-team-api';

vi.mock('@/lib/workspace-team-api', () => ({
  workspaceTeamApi: { listMemberDetails: vi.fn() },
}));

afterEach(() => { cleanup(); vi.resetAllMocks(); });

it('shows disabled account members without presenting them as active', async () => {
  vi.mocked(workspaceTeamApi.listMemberDetails).mockResolvedValue([{
    userId: 'disabled-member', name: 'Unavailable Member', email: 'disabled@example.com',
    role: 'workspace_admin', status: 'disabled', mfaEnabled: true,
    lastLoginAt: null, invitedByUserId: null, joinedAt: '2026-09-01T00:00:00Z',
  }]);
  render(<WorkspaceMemberDetailsPanel />);
  expect(await screen.findByText('Unavailable Member')).toBeTruthy();
  expect(screen.getByText('disabled')).toBeTruthy();
  expect(screen.queryByText('active')).toBeNull();
  expect(screen.getByRole('columnheader', { name: 'Account last sign-in' })).toBeTruthy();
});
