/* @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { WorkspaceOwnerRecoveryPanel } from './WorkspaceOwnerRecoveryPanel';
import { readStorage } from '@/lib/storage';
import { workspaceTeamApi } from '@/lib/workspace-team-api';
import { recoverWorkspaceOwner } from './workspaceOwnerRecovery.api';

vi.mock('@/lib/storage', () => ({ readStorage: vi.fn() }));
vi.mock('@/lib/workspace-api', () => ({
  activeWorkspaceId: () => 'workspace-1',
  workspacePresentationKey: () => 'session-1',
}));
vi.mock('@/lib/workspace-team-api', () => ({ workspaceTeamApi: { listMemberDetails: vi.fn() } }));
vi.mock('./workspaceOwnerRecovery.api', () => ({ recoverWorkspaceOwner: vi.fn() }));

const activeAdmin = {
  userId: 'admin-2', name: 'Administrator B', email: 'admin-b@example.com',
  role: 'workspace_admin', status: 'active', mfaEnabled: true,
  lastLoginAt: null, invitedByUserId: null, joinedAt: '2026-09-21T00:00:00Z',
};
const props = { workspaceId: 'workspace-1', currentUserId: 'admin-1', canManage: true };
afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe('WorkspaceOwnerRecoveryPanel', () => {
  it('does not expose recovery to non-organization owners or missing permissions', () => {
    vi.mocked(readStorage).mockReturnValue({ user: { role: 'admin' } });
    const onRecovered = vi.fn();
    const view = render(<WorkspaceOwnerRecoveryPanel {...props} onRecovered={onRecovered} />);
    expect(screen.queryByText('Recover unavailable workspace ownership')).toBeNull();
    view.rerender(<WorkspaceOwnerRecoveryPanel {...props} canManage={false} onRecovered={onRecovered} />);
    expect(workspaceTeamApi.listMemberDetails).not.toHaveBeenCalled();
  });

  it('only offers other active administrators and requires typed confirmation', async () => {
    vi.mocked(readStorage).mockReturnValue({ user: { role: 'owner' } });
    vi.mocked(workspaceTeamApi.listMemberDetails).mockResolvedValue([
      activeAdmin,
      { ...activeAdmin, userId: 'admin-3', status: 'suspended', name: 'Suspended' },
      { ...activeAdmin, userId: 'admin-1', name: 'Self' },
      { ...activeAdmin, userId: 'viewer-1', role: 'viewer', name: 'Viewer' },
    ]);
    vi.mocked(recoverWorkspaceOwner).mockResolvedValue({
      ownerUserId: 'admin-2', ownerName: 'Administrator B', creatorUserId: 'admin-1',
    });
    const onRecovered = vi.fn();
    render(<WorkspaceOwnerRecoveryPanel {...props} onRecovered={onRecovered} />);
    expect(await screen.findByRole('option', { name: /Administrator B/ })).toBeTruthy();
    expect(screen.queryByRole('option', { name: /Suspended|Self|Viewer/ })).toBeNull();
    const button = screen.getByRole('button', { name: 'Confirm ownership recovery' }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Recovery administrator'), { target: { value: 'admin-2' } });
    fireEvent.change(screen.getByLabelText('Recovery reason'), { target: { value: 'recorded_owner_unavailable' } });
    fireEvent.change(screen.getByLabelText('Type RECOVER to confirm'), { target: { value: 'RECOVER' } });
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    await waitFor(() => expect(recoverWorkspaceOwner).toHaveBeenCalledWith({
      targetUserId: 'admin-2', reason: 'recorded_owner_unavailable', confirmation: 'RECOVER',
    }));
    expect(recoverWorkspaceOwner).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(onRecovered).toHaveBeenCalledWith(expect.objectContaining({ ownerUserId: 'admin-2' })));
  });

  it('hides the recovery form and shows retry if member details cannot be verified', async () => {
    vi.mocked(readStorage).mockReturnValue({ user: { role: 'owner' } });
    vi.mocked(workspaceTeamApi.listMemberDetails).mockRejectedValue(new Error('Member access unavailable'));
    render(<WorkspaceOwnerRecoveryPanel {...props} onRecovered={vi.fn()} />);
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'Member access unavailable');
    expect(screen.queryByRole('button', { name: 'Confirm ownership recovery' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Retry recovery candidates' })).toBeTruthy();
  });
});
