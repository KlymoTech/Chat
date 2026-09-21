/* @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { WorkspaceMembersPanel } from '@/features/workspace/members/WorkspaceMembersPanel';
import { workspaceTeamApi } from '@/lib/workspace-team-api';

vi.mock('@/components/WorkspaceTeamPanel', () => ({ WorkspaceTeamPanel: () => <div>Legacy team controls</div> }));
vi.mock('@/lib/workspace-api', () => ({ workspacePresentationKey: () => 'scope' }));
vi.mock('@/lib/workspace-team-api', () => ({
  workspaceTeamApi: {
    listMembers: vi.fn(), listMemberLifecycle: vi.fn(), suspendMember: vi.fn(), reactivateMember: vi.fn(),
  },
}));

const workspace = {
  id: 'workspace-1', name: 'Workspace One', slug: 'workspace-one', plan: 'business', memberCount: 2,
  permissions: ['members.view', 'members.manage'],
  preferences: { timezone: 'UTC', defaultLanguage: 'English', dateFormat: 'DD/MM/YYYY' as const },
  security: { sensitiveDataMasking: true, securityContact: null },
  whiteLabel: {
    companyName: 'Northstar AI', logoDataUrl: '', faviconDataUrl: '', appIconDataUrl: '',
    primaryColor: '#0c0b0b', secondaryColor: '#6b6b70', supportEmail: null, supportUrl: '', browserTitle: 'Northstar AI',
    customDomain: '', dnsStatus: 'not-configured' as const, brandedLogin: false, brandedDashboard: true,
    brandedWidget: false, brandedEmails: false, removePlatformBranding: false,
  },
};
const members = [
  { userId: 'self', name: 'Admin', email: 'admin@example.com', role: 'workspace_admin' as const, allAgentsAccess: true, agentIds: [], joinedAt: '2026-01-01T00:00:00Z', isSelf: true },
  { userId: 'member', name: 'Member', email: 'member@example.com', role: 'operator' as const, allAgentsAccess: true, agentIds: [], joinedAt: '2026-01-01T00:00:00Z', isSelf: false },
];

afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe('WorkspaceMembersPanel lifecycle', () => {
  it('requires reason and typed SUSPEND confirmation before changing access', async () => {
    vi.mocked(workspaceTeamApi.listMembers).mockResolvedValue(members);
    vi.mocked(workspaceTeamApi.listMemberLifecycle).mockResolvedValue([
      { userId: 'self', status: 'active' }, { userId: 'member', status: 'active' },
    ]);
    vi.mocked(workspaceTeamApi.suspendMember).mockResolvedValue({ userId: 'member', status: 'suspended' });
    render(<WorkspaceMembersPanel workspace={workspace} />);
    const suspend = await screen.findByRole('button', { name: 'Suspend' });
    fireEvent.click(suspend);
    const submit = screen.getByRole('button', { name: 'Suspend member' }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Temporary access review' } });
    fireEvent.change(screen.getByLabelText('Type SUSPEND to confirm'), { target: { value: 'SUSPEND' } });
    expect(submit.disabled).toBe(false);
    fireEvent.click(submit);
    await waitFor(() => expect(workspaceTeamApi.suspendMember).toHaveBeenCalledWith('member', 'Temporary access review'));
    expect(await screen.findByText('suspended')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Suspend member' })).toBeNull();
  });

  it('shows a retryable load error and never offers self suspension', async () => {
    vi.mocked(workspaceTeamApi.listMembers).mockRejectedValue(new Error('Lifecycle unavailable'));
    vi.mocked(workspaceTeamApi.listMemberLifecycle).mockResolvedValue([]);
    render(<WorkspaceMembersPanel workspace={workspace} />);
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', expect.stringContaining('Lifecycle unavailable'));
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy();
  });
});
