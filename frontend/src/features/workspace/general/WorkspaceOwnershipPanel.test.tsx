/* @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { WorkspaceOwnershipPanel } from '@/features/workspace/general/WorkspaceOwnershipPanel';
import { workspaceApi } from '@/lib/workspace-api';
import { workspaceTeamApi } from '@/lib/workspace-team-api';

vi.mock('@/lib/workspace-api', () => ({
  activeWorkspaceId: () => 'workspace-1',
  workspacePresentationKey: () => 'test-scope',
  workspaceApi: {
    getOwner: vi.fn(),
    getTeam: vi.fn(),
    transferOwner: vi.fn(),
  },
}));
vi.mock('@/lib/workspace-team-api', () => ({
  workspaceTeamApi: { listMemberLifecycle: vi.fn() },
}));

const owner = { ownerUserId: 'owner-a', ownerName: 'Owner A', creatorUserId: 'original-creator' };
const admin = {
  id: 'owner-b', name: 'Owner B', email: 'owner-b@example.com', role: 'workspace_admin',
  tenantRole: 'member', status: 'active',
};

afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe('WorkspaceOwnershipPanel', () => {
  it('lets other workspace members read the owner without showing the transfer form', async () => {
    vi.mocked(workspaceApi.getOwner).mockResolvedValue(owner);
    render(<WorkspaceOwnershipPanel workspaceId="workspace-1" currentUserId="viewer" canManage={false} />);
    expect(await screen.findByText('Owner A')).toBeTruthy();
    expect(screen.queryByText('Transfer workspace ownership')).toBeNull();
    expect(workspaceApi.getTeam).not.toHaveBeenCalled();
    expect(workspaceTeamApi.listMemberLifecycle).not.toHaveBeenCalled();
  });

  it('requires recovery rather than granting the creator an implicit transfer form', async () => {
    vi.mocked(workspaceApi.getOwner).mockResolvedValue({
      ownerUserId: null, ownerName: null, creatorUserId: 'original-creator',
    });
    render(<WorkspaceOwnershipPanel workspaceId="workspace-1" currentUserId="original-creator" canManage />);
    expect(await screen.findByText(/Contact your organization administrator to recover ownership/)).toBeTruthy();
    expect(screen.queryByText('Transfer workspace ownership')).toBeNull();
    expect(workspaceApi.getTeam).not.toHaveBeenCalled();
    expect(workspaceApi.transferOwner).not.toHaveBeenCalled();
  });

  it('requires target, reason and typed confirmation before submitting once', async () => {
    vi.mocked(workspaceApi.getOwner).mockResolvedValue(owner);
    vi.mocked(workspaceTeamApi.listMemberLifecycle).mockResolvedValue([
      { userId: 'owner-a', status: 'active' }, { userId: 'owner-b', status: 'active' },
    ]);
    vi.mocked(workspaceApi.getTeam).mockResolvedValue({ members: [
      { ...admin, id: 'owner-a', name: 'Owner A' }, admin,
    ], invitations: [] });
    vi.mocked(workspaceApi.transferOwner).mockResolvedValue({
      ownerUserId: 'owner-b', ownerName: 'Owner B', creatorUserId: 'original-creator',
    });
    render(<WorkspaceOwnershipPanel workspaceId="workspace-1" currentUserId="owner-a" canManage />);
    expect(await screen.findByText('Owner A')).toBeTruthy();
    fireEvent.click(screen.getByText('Transfer workspace ownership'));
    expect(await screen.findByRole('option', { name: /Owner B/ })).toBeTruthy();
    const confirmButton = screen.getByRole('button', { name: 'Confirm ownership transfer' }) as HTMLButtonElement;
    expect(confirmButton.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('New workspace owner'), { target: { value: 'owner-b' } });
    fireEvent.change(screen.getByLabelText('Transfer reason'), { target: { value: 'administrative_handover' } });
    fireEvent.change(screen.getByLabelText('Type TRANSFER to confirm'), { target: { value: 'TRANSFER' } });
    expect(confirmButton.disabled).toBe(false);
    fireEvent.click(confirmButton);
    await waitFor(() => expect(workspaceApi.transferOwner).toHaveBeenCalledWith({
      expectedOwnerUserId: 'owner-a', targetUserId: 'owner-b',
      reason: 'administrative_handover', confirmation: 'TRANSFER',
    }));
    expect(workspaceApi.transferOwner).toHaveBeenCalledTimes(1);
    expect(await screen.findByText('Workspace ownership transferred. Your administrator access is unchanged.')).toBeTruthy();
  });

  it('keeps the existing owner visible when the ownership endpoint rejects a transfer', async () => {
    vi.mocked(workspaceApi.getOwner).mockResolvedValue(owner);
    vi.mocked(workspaceTeamApi.listMemberLifecycle).mockResolvedValue([{ userId: 'owner-b', status: 'active' }]);
    vi.mocked(workspaceApi.getTeam).mockResolvedValue({ members: [admin], invitations: [] });
    vi.mocked(workspaceApi.transferOwner).mockRejectedValue(new Error('Workspace owner changed; reload before transferring'));
    render(<WorkspaceOwnershipPanel workspaceId="workspace-1" currentUserId="owner-a" canManage />);
    fireEvent.click(await screen.findByText('Transfer workspace ownership'));
    await screen.findByRole('option', { name: /Owner B/ });
    fireEvent.change(screen.getByLabelText('New workspace owner'), { target: { value: 'owner-b' } });
    fireEvent.change(screen.getByLabelText('Transfer reason'), { target: { value: 'responsibility_change' } });
    fireEvent.change(screen.getByLabelText('Type TRANSFER to confirm'), { target: { value: 'TRANSFER' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm ownership transfer' }));
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'Workspace owner changed; reload before transferring');
    expect(screen.getByText('Owner A')).toBeTruthy();
  });

  it('never offers suspended administrators as transfer targets', async () => {
    vi.mocked(workspaceApi.getOwner).mockResolvedValue(owner);
    vi.mocked(workspaceApi.getTeam).mockResolvedValue({ members: [admin], invitations: [] });
    vi.mocked(workspaceTeamApi.listMemberLifecycle).mockResolvedValue([{ userId: 'owner-b', status: 'suspended' }]);
    render(<WorkspaceOwnershipPanel workspaceId="workspace-1" currentUserId="owner-a" canManage />);
    fireEvent.click(await screen.findByText('Transfer workspace ownership'));
    expect(await screen.findByText(/Invite or promote another active workspace administrator/)).toBeTruthy();
    expect(screen.queryByRole('option', { name: /Owner B/ })).toBeNull();
    expect(workspaceApi.transferOwner).not.toHaveBeenCalled();
  });

  it('fails closed if lifecycle status cannot be loaded', async () => {
    vi.mocked(workspaceApi.getOwner).mockResolvedValue(owner);
    vi.mocked(workspaceApi.getTeam).mockResolvedValue({ members: [admin], invitations: [] });
    vi.mocked(workspaceTeamApi.listMemberLifecycle).mockRejectedValue(new Error('Lifecycle unavailable'));
    render(<WorkspaceOwnershipPanel workspaceId="workspace-1" currentUserId="owner-a" canManage />);
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'Lifecycle unavailable');
    expect(screen.queryByText('Transfer workspace ownership')).toBeNull();
    expect(screen.getByRole('button', { name: 'Retry loading owner' })).toBeTruthy();
  });
});
