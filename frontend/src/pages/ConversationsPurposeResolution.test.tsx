import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { demoAgents } from '@/lib/demo-data';
import { ConversationsPage } from '@/pages/ConversationsPage';
import type { Agent, Conversation, PageResult } from '@/types';

const mocks = vi.hoisted(() => ({
  pushToast: vi.fn(),
  agentList: vi.fn<() => Promise<Agent[]>>(),
  conversationList: vi.fn<() => Promise<PageResult<Conversation>>>(),
  resolve: vi.fn<(conversationId: string, leadStatus?: string) => Promise<Conversation>>(),
  resolveEducationSalesIntent: vi.fn(),
  educationSalesSettings: vi.fn(),
  updateState: vi.fn(),
  reply: vi.fn(),
}));

vi.mock('@/components/providers', () => ({
  useToast: () => ({ pushToast: mocks.pushToast }),
  useWorkspace: () => ({
    activeWorkspace: { id: 'workspace-1', name: 'NorthStar Academy' },
  }),
}));

vi.mock('@/lib/api', () => ({
  api: {
    agents: { list: mocks.agentList },
    conversations: {
      updateState: mocks.updateState,
      reply: mocks.reply,
    },
  },
}));

vi.mock('@/lib/conversation-api', () => ({
  conversationApi: {
    list: mocks.conversationList,
    resolve: mocks.resolve,
    resolveEducationSalesIntent: mocks.resolveEducationSalesIntent,
  },
}));

vi.mock('@/lib/education-sales-settings-api', () => ({
  educationSalesSettingsApi: {
    get: mocks.educationSalesSettings,
  },
}));

const baseConversation: Conversation = {
  canUpdateLeadStatus: true,
  id: 'conversation-1',
  workspaceId: 'workspace-1',
  agentId: 'agent-1',
  visitorName: 'Student One',
  visitorEmail: 'student@example.com',
  channel: 'widget',
  state: 'open',
  sentiment: 'neutral',
  preview: 'Can you help me?',
  unread: 0,
  startedAt: '2026-09-10T00:00:00.000Z',
  updatedAt: '2026-09-10T00:01:00.000Z',
  messages: [],
};

function agentForPurpose(purpose: Agent['purpose']): Agent {
  return {
    ...structuredClone(demoAgents[0]!),
    id: 'agent-1',
    purpose,
  };
}

async function renderAndResolve(purpose: Agent['purpose']): Promise<void> {
  const agent = agentForPurpose(purpose);
  mocks.agentList.mockResolvedValue([agent]);
  mocks.conversationList.mockResolvedValue({
    items: [baseConversation],
    total: 1,
    page: 1,
    pageSize: 50,
  });
  mocks.resolve.mockResolvedValue({ ...baseConversation, state: 'resolved' });

  const user = userEvent.setup();
  render(
    <MemoryRouter>
      <ConversationsPage />
    </MemoryRouter>,
  );
  await user.click(await screen.findByRole('button', { name: 'Resolve' }));
  await waitFor(() => expect(mocks.resolve).toHaveBeenCalledWith(baseConversation.id, 'new'));
}

describe('ConversationsPage purpose-aware resolution feedback', () => {
  beforeEach(() => {
    mocks.educationSalesSettings.mockResolvedValue({ createUpsellLeads: false });
    mocks.resolveEducationSalesIntent.mockResolvedValue({
      conversationId: baseConversation.id,
      state: 'resolved',
      leadId: 'lead-1',
      leadCreated: true,
    });
    mocks.updateState.mockResolvedValue(baseConversation);
    mocks.reply.mockResolvedValue(undefined);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('confirms a saved lead for Education resolution', async () => {
    await renderAndResolve('education');
    expect(mocks.pushToast).toHaveBeenCalledWith(
      'Conversation resolved and lead saved in Leads',
    );
    expect(mocks.resolveEducationSalesIntent).not.toHaveBeenCalled();
  });

  it('preserves the Lead Generation finalized-lead confirmation', async () => {
    await renderAndResolve('lead_generation');
    expect(mocks.pushToast).toHaveBeenCalledWith('Conversation resolved and lead saved in Leads');
  });

  it('uses a neutral confirmation for Support', async () => {
    await renderAndResolve('support');
    expect(mocks.pushToast).toHaveBeenCalledWith('Conversation resolved and lead saved in Leads');
  });

  it('shows a separate opt-in Education sales action and routes it without normal Resolve', async () => {
    mocks.educationSalesSettings.mockResolvedValue({ createUpsellLeads: true });
    mocks.agentList.mockResolvedValue([agentForPurpose('education')]);
    mocks.conversationList.mockResolvedValue({
      items: [baseConversation],
      total: 1,
      page: 1,
      pageSize: 50,
    });

    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <ConversationsPage />
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole('button', { name: 'Resolve + sales lead' }));

    await waitFor(() => {
      expect(mocks.resolveEducationSalesIntent).toHaveBeenCalledWith(baseConversation.id);
    });
    expect(mocks.resolve).not.toHaveBeenCalled();
    expect(mocks.pushToast).toHaveBeenCalledWith(
      'Education conversation resolved and sales Lead created',
    );
  });

  it('sends Qualified with Resolve in a single request and reports queued sync', async () => {
    mocks.agentList.mockResolvedValue([agentForPurpose('support')]);
    mocks.conversationList.mockResolvedValue({ items: [baseConversation], total: 1, page: 1, pageSize: 50 });
    mocks.resolve.mockResolvedValue({ ...baseConversation, state: 'resolved', leadId: 'lead-1', leadStatus: 'qualified' });
    const user = userEvent.setup();
    render(<MemoryRouter><ConversationsPage /></MemoryRouter>);
    await user.selectOptions(await screen.findByRole('combobox', { name: 'Lead status' }), 'qualified');
    expect(mocks.resolve).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Resolve' }));
    await waitFor(() => expect(mocks.resolve).toHaveBeenCalledExactlyOnceWith(baseConversation.id, 'qualified'));
    expect(mocks.pushToast).toHaveBeenCalledWith(expect.stringContaining('Automatic CRM sync requested'));
    expect(mocks.updateState).not.toHaveBeenCalled();
  });

  it('loads existing lead status and saves changes on an already resolved conversation', async () => {
    const conversation = { ...baseConversation, state: 'resolved' as const, leadId: 'lead-1', leadStatus: 'contacted' };
    mocks.agentList.mockResolvedValue([agentForPurpose('support')]);
    mocks.conversationList.mockResolvedValue({ items: [conversation], total: 1, page: 1, pageSize: 50 });
    mocks.resolve.mockResolvedValue({ ...conversation, leadStatus: 'qualified' });
    const user = userEvent.setup();
    render(<MemoryRouter><ConversationsPage /></MemoryRouter>);
    const status = await screen.findByRole('combobox', { name: 'Lead status' });
    expect(status).toHaveValue('contacted');
    await user.selectOptions(status, 'qualified');
    await user.click(screen.getByRole('button', { name: 'Save status' }));
    await waitFor(() => expect(mocks.resolve).toHaveBeenCalledWith(baseConversation.id, 'qualified'));
    expect(mocks.updateState).not.toHaveBeenCalled();
  });

  it('keeps the selected status for retry and reports save errors', async () => {
    mocks.agentList.mockResolvedValue([agentForPurpose('support')]);
    mocks.conversationList.mockResolvedValue({ items: [baseConversation], total: 1, page: 1, pageSize: 50 });
    mocks.resolve.mockRejectedValueOnce(new Error('Connection interrupted'));
    const user = userEvent.setup();
    render(<MemoryRouter><ConversationsPage /></MemoryRouter>);
    await user.selectOptions(await screen.findByRole('combobox', { name: 'Lead status' }), 'qualified');
    await user.click(screen.getByRole('button', { name: 'Resolve' }));
    await waitFor(() => expect(mocks.pushToast).toHaveBeenCalledWith('Connection interrupted', 'error'));
    expect(screen.getByRole('combobox', { name: 'Lead status' })).toHaveValue('qualified');
    expect(screen.getByRole('button', { name: 'Resolve' })).toBeEnabled();
  });

  it('disables the status selector when the user cannot edit leads', async () => {
    mocks.agentList.mockResolvedValue([agentForPurpose('support')]);
    mocks.conversationList.mockResolvedValue({ items: [{ ...baseConversation, canUpdateLeadStatus: false }], total: 1, page: 1, pageSize: 50 });
    mocks.resolve.mockResolvedValue({ ...baseConversation, state: 'resolved' });
    const user = userEvent.setup();
    render(<MemoryRouter><ConversationsPage /></MemoryRouter>);
    expect(await screen.findByRole('combobox', { name: 'Lead status' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Resolve' }));
    await waitFor(() => expect(mocks.resolve).toHaveBeenCalledWith(baseConversation.id, undefined));
  });

});
