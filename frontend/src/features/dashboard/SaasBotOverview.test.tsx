import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { OverviewPage } from '@/pages/OverviewPage';
import { demoAgents, demoAnalytics } from '@/lib/demo-data';

const mocks = vi.hoisted(() => ({
  agents: vi.fn(), analytics: vi.fn(), conversations: vi.fn(), knowledge: vi.fn(), integrations: vi.fn(),
  workspaceId: 'workspace-a', role: 'owner', permissions: ['*'] as string[],
}));
vi.mock('@/components/providers', () => ({
  useAuth: () => ({ session: { user: { name: 'Review Owner', role: mocks.role } } }),
  useWorkspace: () => ({ activeWorkspace: { id: mocks.workspaceId, name: mocks.workspaceId, permissions: mocks.permissions } }),
}));
vi.mock('@/lib/api', () => ({ api: {
  agents: { list: mocks.agents }, analytics: { summary: mocks.analytics }, conversations: { list: mocks.conversations },
  knowledge: { list: mocks.knowledge }, integrations: { list: mocks.integrations },
} }));
vi.mock('@/lib/attention-api', () => ({ loadAttentionConversations: mocks.conversations }));
afterEach(cleanup);
beforeEach(() => {
  vi.resetAllMocks();
  mocks.workspaceId = 'workspace-a'; mocks.role = 'owner'; mocks.permissions = ['*'];
  mocks.agents.mockResolvedValue([{ ...structuredClone(demoAgents[0]!), id: 'agent-a', name: 'Live assistant', status: 'active' }]);
  mocks.analytics.mockResolvedValue({ ...demoAnalytics, conversations: 23, avgResponseSeconds: 1.25, resolutionRate: 40 });
  mocks.conversations.mockResolvedValue({ items: [], total: 0 });
  mocks.knowledge.mockResolvedValue([{ id: 'source-a', status: 'ready', updatedAt: '2026-10-01T10:00:00Z' }, { id: 'source-b', status: 'failed', updatedAt: '2026-10-02T10:00:00Z' }]);
  mocks.integrations.mockResolvedValue([{ id: 'whatsapp', name: 'WhatsApp', category: 'channel', connected: true }, { id: 'slack', name: 'Slack', category: 'channel', connected: false }]);
});
function mount() { return render(<MemoryRouter><OverviewPage /></MemoryRouter>); }

describe('SaaS Bot overview API fidelity', () => {
  it('uses real metrics, selected-agent knowledge and actual connection status', async () => {
    mount();
    expect(await within(screen.getByRole('article', { name: 'Conversations' })).findByText('23')).toBeInTheDocument();
    expect(within(screen.getByRole('article', { name: 'Average response' })).getByText('1.25s')).toBeInTheDocument();
    expect(within(screen.getByRole('article', { name: 'Resolved conversations' })).getByText('40%')).toBeInTheDocument();
    const progress = await screen.findByRole('progressbar', { name: 'Ready knowledge sources for Live assistant' });
    expect(progress).toHaveAttribute('value', '1'); expect(progress).toHaveAttribute('max', '2');
    expect(mocks.knowledge).toHaveBeenCalledWith('agent-a');
    expect(screen.getByText('WhatsApp').closest('li')).toHaveTextContent('Connected');
    expect(screen.getByText('Slack').closest('li')).toHaveTextContent('Not connected');
    expect(screen.getByRole('link', { name: /Manage knowledge/ })).toHaveAttribute('href', '/agents/agent-a/knowledge');
    expect(screen.getByRole('link', { name: /Create agent/ })).toHaveAttribute('href', '/agents?create=1');
  });
  it('reports failures and retries rather than showing design sample data', async () => {
    mocks.analytics.mockRejectedValueOnce(new Error('Analytics temporarily offline'));
    mount();
    expect(await screen.findByText('Analytics temporarily offline')).toBeInTheDocument();
    expect(within(screen.getByRole('article', { name: 'Conversations' })).getByText('—')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await within(screen.getByRole('article', { name: 'Conversations' })).findByText('23')).toBeInTheDocument();
  });
  it('does not present a previous period as fresh data after a failed range change', async () => {
    mount();
    await within(screen.getByRole('article', { name: 'Conversations' })).findByText('23');
    mocks.analytics.mockRejectedValueOnce(new Error('Monthly report unavailable'));
    await userEvent.selectOptions(screen.getByLabelText('Chart period'), '30');
    expect(await screen.findByText('Monthly report unavailable')).toBeInTheDocument();
    expect(within(screen.getByRole('article', { name: 'Conversations' })).queryByText('23')).not.toBeInTheDocument();
    expect(within(screen.getByRole('article', { name: 'Conversations' })).getByText('—')).toBeInTheDocument();
  });
  it('does not call endpoints unavailable to a restricted member', async () => {
    mocks.role = 'member'; mocks.permissions = ['workspace.view'];
    mount();
    expect(await screen.findByText('Agent access is required to view your agents.')).toBeInTheDocument();
    expect(mocks.agents).not.toHaveBeenCalled(); expect(mocks.analytics).not.toHaveBeenCalled();
    expect(mocks.conversations).not.toHaveBeenCalled(); expect(mocks.integrations).not.toHaveBeenCalled();
    expect(mocks.knowledge).not.toHaveBeenCalled();
    expect(screen.queryByRole('link', { name: /Create agent/ })).not.toBeInTheDocument();
  });
  it('honors an explicit workspace viewer scope even for an organization owner', async () => {
    mocks.permissions = ['workspace.view', 'agents.view'];
    mount();
    expect(await screen.findByRole('link', { name: 'Open Live assistant' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Create agent/ })).not.toBeInTheDocument();
    expect(mocks.analytics).not.toHaveBeenCalled(); expect(mocks.knowledge).not.toHaveBeenCalled();
    expect(mocks.conversations).not.toHaveBeenCalled(); expect(mocks.integrations).not.toHaveBeenCalled();
  });
  it('remounts the dashboard for a new workspace instead of exposing previous data', async () => {
    const view = mount();
    expect(await screen.findByRole('link', { name: 'Open Live assistant' })).toBeInTheDocument();
    mocks.workspaceId = 'workspace-b';
    mocks.agents.mockResolvedValue([]); mocks.analytics.mockResolvedValue({ ...demoAnalytics, conversations: 0 });
    view.rerender(<MemoryRouter><OverviewPage /></MemoryRouter>);
    expect(screen.queryByRole('link', { name: 'Open Live assistant' })).not.toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Create your first agent' })).toBeInTheDocument();
    expect(await within(screen.getByRole('article', { name: 'Conversations' })).findByText('0')).toBeInTheDocument();
  });
  it('shows source retrieval errors, not a misleading healthy zero-source state', async () => {
    mocks.knowledge.mockRejectedValueOnce(new Error('Knowledge permission expired'));
    mount();
    expect(await screen.findByText('Knowledge permission expired')).toBeInTheDocument();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('progressbar')).toHaveAttribute('value', '1');
  });
});
