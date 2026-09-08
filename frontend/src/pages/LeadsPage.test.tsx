import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ToastProvider } from '@/components/providers';
import { demoAgents, demoLeads } from '@/lib/demo-data';
import { LeadsPage } from '@/pages/LeadsPage';
import type { Agent, Lead, PageResult } from '@/types';

interface LeadFilters {
  page?: number;
  pageSize?: number;
  search?: string;
  status?: string;
  agentId?: string;
}

const apiMocks = vi.hoisted(() => ({
  listLeads: vi.fn<(filters?: LeadFilters) => Promise<PageResult<Lead>>>(),
  listAgents: vi.fn<() => Promise<Agent[]>>(),
  updateStatus: vi.fn<(leadId: string, status: string) => Promise<Lead>>(),
  deliveriesForLead: vi.fn<() => Promise<never[]>>(),
  activityForLead: vi.fn<() => Promise<never[]>>(),
  syncLead: vi.fn<() => Promise<Record<string, never>>>(),
  retryDelivery: vi.fn<() => Promise<Record<string, never>>>(),
}));

vi.mock('@/lib/api', () => ({
  api: {
    agents: { list: apiMocks.listAgents },
    leads: { updateStatus: apiMocks.updateStatus },
  },
}));

vi.mock('@/lib/lead-crm-api', () => ({
  leadCrmApi: {
    leads: apiMocks.listLeads,
    deliveriesForLead: apiMocks.deliveriesForLead,
    activityForLead: apiMocks.activityForLead,
    syncLead: apiMocks.syncLead,
    retryDelivery: apiMocks.retryDelivery,
  },
}));

describe('LeadsPage', () => {
  beforeEach(() => {
    const leads = structuredClone(demoLeads);
    apiMocks.listAgents.mockResolvedValue(structuredClone(demoAgents));
    apiMocks.listLeads.mockImplementation(async (filters = {}) => {
      const search = filters.search?.trim().toLowerCase();
      const status = filters.status;
      const items = leads.filter((lead) => {
        const matchesSearch = !search || `${lead.name ?? ''} ${lead.email ?? ''} ${lead.phone ?? ''}`.toLowerCase().includes(search);
        const matchesStatus = !status || status === 'all' || lead.status === status;
        return matchesSearch && matchesStatus;
      });
      return { items, total: items.length, page: filters.page ?? 1, pageSize: filters.pageSize ?? 50 };
    });
    apiMocks.updateStatus.mockImplementation(async (leadId, status) => ({ ...leads.find((lead) => lead.id === leadId)!, status }));
    apiMocks.deliveriesForLead.mockResolvedValue([]);
    apiMocks.activityForLead.mockResolvedValue([]);
    apiMocks.syncLead.mockResolvedValue({});
    apiMocks.retryDelivery.mockResolvedValue({});
  });

  afterEach(cleanup);

  it('filters captured contacts through the server API and persists a status change', async () => {
    const user = userEvent.setup();
    render(<ToastProvider><LeadsPage /></ToastProvider>);

    expect(await screen.findByText('Nora Reed')).toBeInTheDocument();
    await user.type(screen.getByLabelText('Search leads'), 'Arjun');
    expect(await screen.findByText('Arjun Mehta')).toBeInTheDocument();
    expect(screen.queryByText('Nora Reed')).not.toBeInTheDocument();
    await waitFor(() => expect(apiMocks.listLeads).toHaveBeenCalledWith(expect.objectContaining({ search: 'Arjun' })));

    await user.clear(screen.getByLabelText('Search leads'));
    expect(await screen.findByText('Nora Reed')).toBeInTheDocument();
    await user.selectOptions(screen.getByRole('combobox', { name: 'Status for Nora Reed' }), 'converted');
    await waitFor(() => expect(apiMocks.updateStatus).toHaveBeenCalledWith('lead-1', 'converted'));
  });
});
