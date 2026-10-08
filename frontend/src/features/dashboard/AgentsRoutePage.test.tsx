import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AgentsRoutePage } from './AgentsRoutePage';
import { demoAgents } from '@/lib/demo-data';
import type { Agent } from '@/types';

const mocks = vi.hoisted(() => ({ pushToast: vi.fn(), permissions: ['*'] as string[], purpose: 'support' as Agent['purpose'] }));
vi.mock('@/components/providers', () => ({
  useAuth: () => ({ session: { user: { role: 'owner' } } }),
  useWorkspace: () => ({ activeWorkspace: { permissions: mocks.permissions } }),
  useToast: () => ({ pushToast: mocks.pushToast }),
}));
vi.mock('@/pages/AgentsPage', () => ({
  AgentsPage: () => <h2>Existing agents list</h2>,
  CreateAgentModal: ({ onClose, onCreated }: { onClose: () => void; onCreated: (agent: Agent) => void }) => <div role="dialog" aria-label="Existing creation workflow"><button onClick={onClose}>Cancel</button><button onClick={() => onCreated({ ...demoAgents[0]!, id: 'created', purpose: mocks.purpose })}>Complete creation</button></div>,
}));
function Location() { const location = useLocation(); return <output aria-label="Current URL">{location.pathname}{location.search}</output>; }
function mount(entry = '/agents?create=1') {
  return render(<MemoryRouter initialEntries={[entry]}><Location /><Routes><Route path="/agents" element={<AgentsRoutePage />} /><Route path="/agents/:agentId/instructions" element={<h2>Existing agent builder</h2>} /></Routes></MemoryRouter>);
}
beforeEach(() => { vi.clearAllMocks(); mocks.permissions = ['*']; mocks.purpose = 'support'; });
afterEach(cleanup);
describe('Agent creation deep link', () => {
  it('preserves the existing list on ordinary agent URLs', () => { mount('/agents'); expect(screen.getByRole('heading', { name: 'Existing agents list' })).toBeInTheDocument(); });
  it('opens the existing wizard and removes only its query parameter on cancel', async () => {
    mount('/agents?create=1&search=sales');
    expect(screen.getByRole('dialog', { name: 'Existing creation workflow' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByLabelText('Current URL')).toHaveTextContent('/agents?search=sales');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
  it('navigates to the actual created agent rather than a fixed sample', async () => {
    mount(); await userEvent.click(screen.getByRole('button', { name: 'Complete creation' }));
    expect(screen.getByLabelText('Current URL')).toHaveTextContent('/agents/created/instructions');
    expect(mocks.pushToast).toHaveBeenCalledWith('Agent created');
  });
  it('keeps the existing education draft provisioning message', async () => {
    mocks.purpose = 'education'; mount(); await userEvent.click(screen.getByRole('button', { name: 'Complete creation' }));
    expect(mocks.pushToast).toHaveBeenCalledWith('Education agent created in draft for safe provisioning');
  });
  it('does not open a creation wizard for an explicit workspace viewer', async () => {
    mocks.permissions = ['agents.view']; mount();
    expect(screen.getByRole('heading', { name: 'Agent creation access required' })).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Back to agents' }));
    expect(screen.getByRole('heading', { name: 'Existing agents list' })).toBeInTheDocument();
  });
});
