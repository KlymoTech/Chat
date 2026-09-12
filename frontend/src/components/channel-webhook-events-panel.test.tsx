import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ChannelWebhookEventsPanel } from '@/components/channel-webhook-events-panel';

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
}));

vi.mock('@/lib/channel-webhook-events-api', () => ({
  channelWebhookEventsApi: { list: mocks.list },
}));

const connections = [
  { id: 'telegram-1', name: 'Student Telegram', provider: 'telegram' },
  { id: 'slack-1', name: 'Support Slack', provider: 'slack' },
];

const events = [{
  id: 'event-1',
  connection_id: 'slack-1',
  provider: 'slack',
  event_type: 'message.received',
  verification_status: 'verified',
  processing_status: 'failed',
  attempt_count: 2,
  error_code: 'processing_failed',
  correlation_id: 'corr-safe-1',
  received_at: '2026-09-12T13:00:00Z',
  processed_at: null,
}];

describe('ChannelWebhookEventsPanel', () => {
  beforeEach(() => {
    mocks.list.mockResolvedValue(events);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('renders only safe operational webhook evidence', async () => {
    render(<ChannelWebhookEventsPanel connections={connections} />);

    expect(await screen.findByText('Support Slack')).toBeInTheDocument();
    expect(screen.getByText('message.received')).toBeInTheDocument();
    expect(screen.getByText('processing_failed')).toBeInTheDocument();
    expect(screen.getByText('Correlation corr-safe-1')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.queryByText('raw provider error')).not.toBeInTheDocument();
    expect(screen.queryByText('private message')).not.toBeInTheDocument();
    expect(mocks.list).toHaveBeenCalledWith({
      connectionId: undefined,
      processingStatus: undefined,
      provider: undefined,
      limit: 100,
    });
  });

  it('reloads using selected status, provider, and connection filters', async () => {
    const user = userEvent.setup();
    render(<ChannelWebhookEventsPanel connections={connections} />);

    await screen.findByText('Support Slack');
    await user.selectOptions(screen.getByLabelText('Channel webhook processing status'), 'failed');
    await waitFor(() => expect(mocks.list).toHaveBeenLastCalledWith({
      connectionId: undefined,
      processingStatus: 'failed',
      provider: undefined,
      limit: 100,
    }));

    await user.selectOptions(screen.getByLabelText('Channel webhook provider'), 'slack');
    await waitFor(() => expect(mocks.list).toHaveBeenLastCalledWith({
      connectionId: undefined,
      processingStatus: 'failed',
      provider: 'slack',
      limit: 100,
    }));

    await user.selectOptions(screen.getByLabelText('Channel webhook connection'), 'slack-1');
    await waitFor(() => expect(mocks.list).toHaveBeenLastCalledWith({
      connectionId: 'slack-1',
      processingStatus: 'failed',
      provider: 'slack',
      limit: 100,
    }));
  });

  it('refreshes the current webhook activity view on demand', async () => {
    const user = userEvent.setup();
    render(<ChannelWebhookEventsPanel connections={connections} />);

    await screen.findByText('Support Slack');
    await user.click(screen.getByRole('button', { name: 'Refresh' }));
    await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(2));
  });

  it('shows an explicit empty state', async () => {
    mocks.list.mockResolvedValue([]);
    render(<ChannelWebhookEventsPanel connections={connections} />);

    expect(await screen.findByText('No channel webhook events found')).toBeInTheDocument();
  });
});
