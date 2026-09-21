/* @vitest-environment jsdom */
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { WorkspaceTeamPanel } from '@/components/WorkspaceTeamPanel';
import type { WorkspaceSettings } from '@/lib/workspace-api';
import { workspaceTeamApi } from '@/lib/workspace-team-api';

vi.mock('@/components/providers', () => ({ useToast: () => ({ pushToast: vi.fn() }) }));
vi.mock('@/lib/api', () => ({ api: { agents: { list: vi.fn().mockResolvedValue([]) } } }));
vi.mock('@/lib/workspace-api', () => ({ workspacePresentationKey: () => 'account-status-test' }));
vi.mock('@/lib/workspace-team-api', () => ({
  workspaceTeamApi: {
    listMembers: vi.fn(), listInvitations: vi.fn(),
  },
  invitationDeliveryNotice: vi.fn(),
}));

afterEach(() => { cleanup(); vi.resetAllMocks(); });

it('does not claim a globally enabled member has active Workspace access', async () => {
  vi.mocked(workspaceTeamApi.listMembers).mockResolvedValue([
    {
      userId: 'admin', name: 'Admin', email: 'admin@example.test',
      role: 'workspace_admin', allAgentsAccess: true, agentIds: [],
      joinedAt: '2026-09-01T00:00:00Z', isSelf: true,
    },
    {
      userId: 'suspended-member', name: 'Suspended in Workspace',
      email: 'member@example.test', role: 'operator', allAgentsAccess: true,
      agentIds: [], joinedAt: '2026-09-01T00:00:00Z', isSelf: false,
    },
  ]);
  vi.mocked(workspaceTeamApi.listInvitations).mockResolvedValue([]);
  const workspace = {
    id: 'workspace-one', name: 'Workspace One',
    permissions: ['members.view', 'members.manage'],
  } as WorkspaceSettings;
  render(<WorkspaceTeamPanel workspace={workspace} />);

  expect(await screen.findByText('Suspended in Workspace')).toBeInTheDocument();
  expect(screen.getByText('Account-enabled members')).toBeInTheDocument();
  expect(screen.getAllByText('Account enabled')).toHaveLength(2);
  expect(screen.queryByText('Active')).not.toBeInTheDocument();
  // Existing role/agent-access editing remains available; the separate
  // Workspace lifecycle panel owns the active/suspended/disabled projection.
  expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument();
});
