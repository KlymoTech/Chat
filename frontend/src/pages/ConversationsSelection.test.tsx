import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ConversationsPage } from './ConversationsPage';
import type { Conversation } from '@/types';

const mocks = vi.hoisted(() => ({ list: vi.fn(), get: vi.fn(), reply: vi.fn(), toast: vi.fn() }));
vi.mock('@/components/providers', () => ({
  useToast: () => ({ pushToast: mocks.toast }),
  useWorkspace: () => ({ activeWorkspace: { id: 'workspace-a', name: 'Test workspace' } }),
}));
vi.mock('@/lib/api', () => ({ api: {
  agents: { list: async () => [] }, conversations: { reply: mocks.reply, updateState: vi.fn() },
} }));
vi.mock('@/lib/conversation-api', () => ({ conversationApi: { list: mocks.list, get: mocks.get } }));
vi.mock('@/lib/lead-crm-api', () => ({ leadCrmApi: { channelProviders: async () => [] } }));
// Assignment has its own permission/API tests; this suite exercises selection and replies.
vi.mock('@/features/workspace/conversations/ConversationAssignmentControl', () => ({
  ConversationAssignmentControl: () => null,
}));

function conversation(id: string): Conversation {
  return {
    id, workspaceId: 'workspace-a', agentId: 'agent-a', visitorName: `Visitor ${id}`,
    channel: 'widget', state: 'open', sentiment: 'neutral', preview: `Preview ${id}`,
    unread: 0, startedAt: '2026-10-08T10:00:00Z', updatedAt: '2026-10-08T10:00:00Z',
    messages: [{ id: `message-${id}`, role: 'user', content: `Message for ${id}`, createdAt: '2026-10-08T10:00:00Z' }],
  };
}
function Navigation() {
  const navigate = useNavigate();
  return <><output aria-label="Current route">{useLocation().search}</output>
    <button onClick={() => navigate('?selected=older&source=overview')}>Open older conversation</button>
    <button onClick={() => navigate('?view=list')}>Show inbox list</button></>;
}
function mount(search = '?selected=older&source=overview') {
  return render(<MemoryRouter initialEntries={[`/conversations${search}`]}><Navigation /><ConversationsPage /></MemoryRouter>);
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
beforeEach(() => {
  vi.resetAllMocks();
  mocks.list.mockResolvedValue({ items: [conversation('recent')], total: 101, page: 1, pageSize: 100 });
  mocks.get.mockImplementation(async (id: string) => conversation(id));
  mocks.reply.mockResolvedValue({});
});
afterEach(cleanup);

describe('inbox selection from the redesigned overview', () => {
  it('keeps a deep link outside the first list page and opens its own detail', async () => {
    mount();
    expect(await screen.findByText('Message for older')).toBeInTheDocument();
    expect(screen.getByLabelText('Current route')).toHaveTextContent('?selected=older&source=overview');
    expect(mocks.get).toHaveBeenCalledWith('older', expect.any(AbortSignal));
    expect(screen.queryByText('Message for recent')).not.toBeInTheDocument();
  });

  it('does not show or reply to the old detail while another deep link loads', async () => {
    const pending = deferred<Conversation>();
    mount('?selected=recent');
    await screen.findByText('Message for recent');
    await userEvent.type(screen.getByPlaceholderText('Reply as a teammate…'), 'Private draft for recent');
    mocks.get.mockImplementation((id: string) => id === 'older' ? pending.promise : Promise.resolve(conversation(id)));
    await userEvent.click(screen.getByRole('button', { name: 'Open older conversation' }));
    expect(screen.queryByText('Message for recent')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send' })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Loading conversation…' })).toBeInTheDocument();
    await act(async () => pending.resolve(conversation('older')));
    expect(await screen.findByText('Message for older')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Reply as a teammate…')).toHaveValue('');
    await userEvent.type(screen.getByPlaceholderText('Reply as a teammate…'), 'Reply for older');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    await waitFor(() => expect(mocks.reply).toHaveBeenCalledWith('older', 'Reply for older'));
  });

  it('does not replace a denied deep link with an unrelated conversation and supports retry', async () => {
    mocks.get.mockRejectedValueOnce(new Error('Conversation request failed (404)'));
    mount();
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Conversation request failed (404)');
    expect(screen.getByLabelText('Current route')).toHaveTextContent('selected=older');
    expect(screen.queryByText('Message for recent')).not.toBeInTheDocument();
    await userEvent.click(within(alert).getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('Message for older')).toBeInTheDocument();
  });

  it('hides cached detail immediately when returning to the mobile list', async () => {
    mount('?selected=recent');
    await screen.findByText('Message for recent');
    await userEvent.click(screen.getByRole('button', { name: 'Show inbox list' }));
    expect(screen.queryByRole('log', { name: 'Conversation messages' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Current route')).toHaveTextContent('?view=list');
  });

  it('auto-selects only when no explicit selection exists, preserving unrelated query parameters', async () => {
    mount('?source=overview');
    await screen.findByText('Message for recent');
    await waitFor(() => expect(screen.getByLabelText('Current route')).toHaveTextContent('selected=recent'));
    expect(screen.getByLabelText('Current route')).toHaveTextContent('source=overview');
  });
});
