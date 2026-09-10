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
  resolve: vi.fn<(conversationId: string) => Promise<Conversation>>(),
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
  },
}));

const baseConversation: Conversation = {
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
  await waitFor(() => expect(mocks.resolve).toHaveBeenCalledWith(baseConversation.id));
}

describe('ConversationsPage purpose-aware resolution feedback', () => {
  beforeEach(() => {
    mocks.updateState.mockResolvedValue(baseConversation);
    mocks.reply.mockResolvedValue(undefined);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('reports Education student-history resolution without claiming a Lead', async () => {
    await renderAndResolve('education');
    expect(mocks.pushToast).toHaveBeenCalledWith(
      'Education conversation resolved and student history updated',
    );
  });

  it('preserves the Lead Generation finalized-lead confirmation', async () => {
    await renderAndResolve('lead_generation');
    expect(mocks.pushToast).toHaveBeenCalledWith('Conversation resolved and lead finalized');
  });

  it('uses a neutral confirmation for Support', async () => {
    await renderAndResolve('support');
    expect(mocks.pushToast).toHaveBeenCalledWith('Conversation resolved');
  });
});
