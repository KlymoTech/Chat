import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CRMManagementPanel } from '@/components/crm-management-panel';

const mocks = vi.hoisted(() => ({
  pushToast: vi.fn(),
  schema: vi.fn(),
  mappings: vi.fn(),
  routes: vi.fn(),
  workspaceSettings: vi.fn(),
  updateWorkspaceSettings: vi.fn(),
  refreshSchema: vi.fn(),
  putMapping: vi.fn(),
  validateMappings: vi.fn(),
  createRoute: vi.fn(),
  updateRoute: vi.fn(),
  deleteRoute: vi.fn(),
  disableConnection: vi.fn(),
}));

vi.mock('@/components/providers', () => ({
  useToast: () => ({ pushToast: mocks.pushToast }),
}));

vi.mock('@/lib/lead-crm-api', () => ({
  leadCrmApi: {
    schema: mocks.schema,
    mappings: mocks.mappings,
    routes: mocks.routes,
    workspaceSettings: mocks.workspaceSettings,
    updateWorkspaceSettings: mocks.updateWorkspaceSettings,
    refreshSchema: mocks.refreshSchema,
    putMapping: mocks.putMapping,
    validateMappings: mocks.validateMappings,
    createRoute: mocks.createRoute,
    updateRoute: mocks.updateRoute,
    deleteRoute: mocks.deleteRoute,
    disableConnection: mocks.disableConnection,
  },
}));

const connection = {
  id: 'connection-1',
  public_id: 'crm_public_1',
  provider: 'zoho' as const,
  name: 'Zoho Production',
  environment: 'production',
  status: 'healthy' as const,
  configuration: {},
  capabilities: {},
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

const settings = {
  connection_id: 'connection-1',
  auto_sync_new_leads: true,
  auto_sync_updates: true,
  updated_at: new Date().toISOString(),
};

describe('CRMManagementPanel auto-sync settings', () => {
  beforeEach(() => {
    mocks.schema.mockResolvedValue({ connectionId: 'connection-1', objectName: 'Leads', fields: [] });
    mocks.mappings.mockResolvedValue([]);
    mocks.routes.mockResolvedValue([]);
    mocks.workspaceSettings.mockResolvedValue(settings);
    mocks.updateWorkspaceSettings.mockImplementation(async (_id: string, patch: Record<string, boolean>) => ({
      ...settings,
      ...patch,
    }));
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('loads workspace auto-sync settings and persists both controls', async () => {
    const user = userEvent.setup();
    render(<CRMManagementPanel connections={[connection]} canManage onConnectionsChanged={vi.fn()} />);

    const newLeads = await screen.findByRole('checkbox', { name: 'Automatically sync new leads' });
    const updates = screen.getByRole('checkbox', { name: 'Automatically sync lead updates' });
    expect(newLeads).toBeChecked();
    expect(updates).toBeChecked();
    expect(mocks.workspaceSettings).toHaveBeenCalledWith('connection-1');

    await user.click(newLeads);
    await waitFor(() => expect(mocks.updateWorkspaceSettings).toHaveBeenCalledWith(
      'connection-1',
      { auto_sync_new_leads: false },
    ));
    await waitFor(() => expect(newLeads).not.toBeChecked());

    await user.click(updates);
    await waitFor(() => expect(mocks.updateWorkspaceSettings).toHaveBeenCalledWith(
      'connection-1',
      { auto_sync_updates: false },
    ));
    expect(mocks.pushToast).toHaveBeenCalledWith('CRM auto-sync settings updated');
  });

  it('keeps auto-sync settings read-only without CRM management permission', async () => {
    render(<CRMManagementPanel connections={[connection]} canManage={false} onConnectionsChanged={vi.fn()} />);

    expect(await screen.findByRole('checkbox', { name: 'Automatically sync new leads' })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: 'Automatically sync lead updates' })).toBeDisabled();
    expect(mocks.updateWorkspaceSettings).not.toHaveBeenCalled();
  });
});
