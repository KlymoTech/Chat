import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CRMDeadLetterPanel } from '@/components/crm-dead-letter-panel';
import type { CRMConnectionView } from '@/lib/lead-crm-api';

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
}));

vi.mock('@/lib/crm-dead-letter-api', () => ({
  crmDeadLetterApi: { list: mocks.list },
}));

const connection: CRMConnectionView = {
  id: 'connection-1',
  public_id: 'crm_public_1',
  provider: 'zoho',
  name: 'Zoho Production',
  environment: 'production',
  status: 'healthy',
  configuration: {},
  capabilities: {},
  created_at: '2026-09-12T08:00:00Z',
  updated_at: '2026-09-12T08:00:00Z',
};

const secondConnection: CRMConnectionView = {
  ...connection,
  id: 'connection-2',
  public_id: 'crm_public_2',
  provider: 'salesforce',
  name: 'Salesforce Production',
};

const openDeadLetter = {
  id: 'dead-letter-1',
  delivery_id: 'delivery-1',
  lead_id: 'lead-1',
  connection_id: 'connection-1',
  provider: 'zoho',
  status: 'open',
  reason_code: 'network_error',
  reason_message: 'Provider timed out',
  created_at: '2026-09-12T08:30:00Z',
  updated_at: '2026-09-12T08:30:00Z',
  resolved_at: null,
};

const resolvedDeadLetter = {
  ...openDeadLetter,
  id: 'dead-letter-2',
  delivery_id: 'delivery-2',
  lead_id: 'lead-2',
  connection_id: 'connection-2',
  provider: 'salesforce',
  status: 'resolved',
  reason_code: 'rate_limit_error',
  reason_message: 'Provider rate limit exhausted',
  resolved_at: '2026-09-12T09:00:00Z',
};

describe('CRMDeadLetterPanel', () => {
  beforeEach(() => {
    mocks.list.mockImplementation(async ({ status, connectionId }: { status?: string; connectionId?: string }) => {
      const rows = [openDeadLetter, resolvedDeadLetter];
      return rows.filter((item) => (
        (!status || status === 'all' || item.status === status)
        && (!connectionId || item.connection_id === connectionId)
      ));
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('loads open dead letters by default and renders safe operational context', async () => {
    render(<CRMDeadLetterPanel connections={[connection, secondConnection]} />);

    expect(await screen.findByText('Provider timed out')).toBeInTheDocument();
    expect(screen.getByText('Zoho Production')).toBeInTheDocument();
    expect(screen.getByText('Lead lead-1')).toBeInTheDocument();
    expect(screen.getByText('Delivery delivery-1')).toBeInTheDocument();
    expect(screen.queryByText('Provider rate limit exhausted')).not.toBeInTheDocument();
    expect(mocks.list).toHaveBeenCalledWith({ status: 'open', connectionId: undefined });
  });

  it('refetches with status and connection filters', async () => {
    const user = userEvent.setup();
    render(<CRMDeadLetterPanel connections={[connection, secondConnection]} />);

    await screen.findByText('Provider timed out');
    await user.selectOptions(screen.getByRole('combobox', { name: 'CRM dead-letter status' }), 'all');
    expect(await screen.findByText('Provider rate limit exhausted')).toBeInTheDocument();
    await waitFor(() => expect(mocks.list).toHaveBeenCalledWith({ status: 'all', connectionId: undefined }));

    await user.selectOptions(screen.getByRole('combobox', { name: 'CRM dead-letter connection' }), 'connection-2');
    await waitFor(() => expect(mocks.list).toHaveBeenCalledWith({ status: 'all', connectionId: 'connection-2' }));
    expect(await screen.findByText('Salesforce Production')).toBeInTheDocument();
    expect(screen.queryByText('Provider timed out')).not.toBeInTheDocument();
  });

  it('shows an explicit healthy empty state when there are no open dead letters', async () => {
    mocks.list.mockResolvedValue([]);
    render(<CRMDeadLetterPanel connections={[connection]} />);

    expect(await screen.findByText('No open CRM dead letters')).toBeInTheDocument();
    expect(screen.getByText('Automatic CRM delivery has no unresolved dead-letter items in this Workspace.')).toBeInTheDocument();
  });
});
