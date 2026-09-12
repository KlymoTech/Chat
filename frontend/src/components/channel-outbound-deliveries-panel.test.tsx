import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ChannelOutboundDeliveriesPanel } from '@/components/channel-outbound-deliveries-panel';

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  requeue: vi.fn(),
  useAuth: vi.fn(),
}));

vi.mock('@/components/providers', () => ({
  useAuth: mocks.useAuth,
}));

vi.mock('@/lib/channel-deliveries-api', () => ({
  channelDeliveriesApi: { list: mocks.list, requeue: mocks.requeue },
}));

const connections = [{
  id: 'channel-1',
  provider: 'telegram',
  name: 'Primary Telegram',
}];

const delivery = {
  id: 'delivery-1',
  connection_id: 'channel-1',
  connection_name: 'Primary Telegram',
  message_id: 'message-safe-reference',
  provider: 'telegram',
  status: 'failed',
  error_code: 'retryable_failure',
  attempt_count: 2,
  dispatch_attempts: 3,
  dispatched_at: '2026-09-12T18:30:00Z',
  processed_at: null,
  next_dispatch_at: '2026-09-12T18:35:00Z',
  created_at: '2026-09-12T18:29:00Z',
  updated_at: '2026-09-12T18:31:00Z',
};

const dispatchFailedDelivery = {
  ...delivery,
  id: 'dispatch-failure-1',
  status: 'dispatch_failed',
  error_code: 'dispatch_failed',
  dispatch_attempts: 8,
  next_dispatch_at: null,
};

describe('ChannelOutboundDeliveriesPanel', () => {
  beforeEach(() => {
    mocks.useAuth.mockReturnValue({ session: { user: { role: 'admin' } } });
    mocks.list.mockResolvedValue([delivery]);
    mocks.requeue.mockResolvedValue({
      ...dispatchFailedDelivery,
      status: 'queued',
      error_code: null,
      dispatch_attempts: 0,
      dispatched_at: null,
      next_dispatch_at: '2026-09-12T18:40:00Z',
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('shows only safe outbound delivery evidence', async () => {
    render(<ChannelOutboundDeliveriesPanel connections={connections} />);

    expect(await screen.findByText('Primary Telegram')).toBeInTheDocument();
    expect(screen.getByText('retryable_failure')).toBeInTheDocument();
    expect(screen.getByText('message-safe-reference')).toBeInTheDocument();
    expect(screen.getByText('Provider 2')).toBeInTheDocument();
    expect(screen.getByText('Dispatch 3')).toBeInTheDocument();
    expect(screen.queryByText('private-recipient-42')).not.toBeInTheDocument();
    expect(screen.queryByText('provider-secret-id')).not.toBeInTheDocument();
    expect(screen.queryByText('Bearer secret-token provider response body')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Requeue dispatch' })).not.toBeInTheDocument();
    expect(mocks.list).toHaveBeenCalledWith({
      connectionId: undefined,
      status: undefined,
      limit: 100,
    });
  });

  it('reloads using selected connection and status filters', async () => {
    const user = userEvent.setup();
    render(<ChannelOutboundDeliveriesPanel connections={connections} />);

    await screen.findByText('message-safe-reference');
    await user.selectOptions(screen.getByLabelText('Channel delivery connection'), 'channel-1');
    await waitFor(() => expect(mocks.list).toHaveBeenLastCalledWith({
      connectionId: 'channel-1',
      status: undefined,
      limit: 100,
    }));

    await user.selectOptions(screen.getByLabelText('Channel delivery status'), 'failed');
    await waitFor(() => expect(mocks.list).toHaveBeenLastCalledWith({
      connectionId: 'channel-1',
      status: 'failed',
      limit: 100,
    }));
  });

  it('refreshes the current delivery view on demand', async () => {
    const user = userEvent.setup();
    render(<ChannelOutboundDeliveriesPanel connections={connections} />);

    await screen.findByText('message-safe-reference');
    await user.click(screen.getByRole('button', { name: 'Refresh deliveries' }));
    await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(2));
  });

  it('lets an admin requeue only an exhausted dispatch failure and reloads evidence', async () => {
    const user = userEvent.setup();
    mocks.list.mockResolvedValue([dispatchFailedDelivery]);
    render(<ChannelOutboundDeliveriesPanel connections={connections} />);

    await screen.findByText('dispatch_failed');
    await user.click(screen.getByRole('button', { name: 'Requeue dispatch' }));

    await waitFor(() => expect(mocks.requeue).toHaveBeenCalledWith('dispatch-failure-1'));
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Dispatch failure requeued through the existing channel dispatcher.',
    );
    await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(2));
  });

  it('keeps the dispatch recovery action hidden from viewers', async () => {
    mocks.useAuth.mockReturnValue({ session: { user: { role: 'member' } } });
    mocks.list.mockResolvedValue([dispatchFailedDelivery]);
    render(<ChannelOutboundDeliveriesPanel connections={connections} />);

    expect(await screen.findByText('dispatch_failed')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Requeue dispatch' })).not.toBeInTheDocument();
    expect(mocks.requeue).not.toHaveBeenCalled();
  });

  it('shows an explicit empty state', async () => {
    mocks.list.mockResolvedValue([]);
    render(<ChannelOutboundDeliveriesPanel connections={[]} />);

    expect(await screen.findByText('No outbound delivery evidence found')).toBeInTheDocument();
  });
});
