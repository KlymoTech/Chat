import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { IntegrationsHubPage } from '@/pages/IntegrationsHubPage';

const mocks = vi.hoisted(() => ({
  resume: vi.fn(), role: 'owner', crm: vi.fn(), channels: vi.fn(), providers: vi.fn(), agents: vi.fn(),
  create: vi.fn(), update: vi.fn(), test: vi.fn(), start: vi.fn(), activate: vi.fn(), entitlements: vi.fn(),
  pushToast: vi.fn(),
  zohoStatus: vi.fn(), zohoStart: vi.fn(), zohoCertify: vi.fn(),
}));
vi.mock('@/components/providers', () => ({ useAuth: () => ({ session: { user: { role: mocks.role } } }), useWorkspace: () => ({ activeWorkspace: { id: 'workspace-1' } }), useToast: () => ({ pushToast: mocks.pushToast }) }));
vi.mock('@/components/whatsapp-integration-modal', () => ({ WhatsAppIntegrationModal: () => null }));
vi.mock('@/lib/api', () => ({ api: { integrations: { list: async () => [] }, agents: { list: mocks.agents } } }));
vi.mock('@/lib/crm-one-click-api', () => ({ crmOneClickApi: { providers: mocks.providers, startOAuth: mocks.start, activateDirect: mocks.activate } }));
vi.mock('@/lib/lead-crm-api', () => ({ leadCrmApi: { startOAuth: mocks.resume, connections: mocks.crm, channelConnections: mocks.channels, createChannelConnection: mocks.create, updateChannelConnection: mocks.update, testChannelConnection: mocks.test, connectionEntitlements: mocks.entitlements } }));
vi.mock('@/lib/zoho-one-click-api', () => ({ zohoOneClickApi: { status: mocks.zohoStatus, start: mocks.zohoStart, certify: mocks.zohoCertify } }));

const saved = { id: 'slack-1', public_id: 'channel-1', provider: 'slack', name: 'Slack', agent_id: 'agent-1', status: 'configured', configuration: {}, webhook_path: '/api/v1/webhooks/channels/tenant/slack/channel-1' };
async function open(name: string) {
  render(<MemoryRouter><IntegrationsHubPage /></MemoryRouter>);
  const button = await screen.findByRole('button', { name: `Connect ${name}` });
  await waitFor(() => expect(button).toBeEnabled());
  await userEvent.click(button);
  return screen.getByRole('dialog');
}
beforeEach(() => {
  mocks.role = 'owner'; mocks.crm.mockResolvedValue([]); mocks.channels.mockResolvedValue([]);
  mocks.zohoStatus.mockResolvedValue({ platformConfigured: true, connected: false, status: 'disconnected', autoSyncNewLeads: false, autoSyncUpdates: false, mappingReady: false, routeReady: false, missingConfiguration: [] });
  mocks.entitlements.mockResolvedValue({ plan: 'business', features: { crm: true, allowedChannels: ['slack', 'telegram', 'instagram', 'facebook'] } });
  mocks.providers.mockResolvedValue([{ id: 'zoho', mode: 'oauth', configured: false, supportsSandbox: true, oauthRedirectUri: 'http://localhost:8100/api/v1/crm/oauth/zoho/callback' }]);
  mocks.agents.mockResolvedValue([{ id: 'agent-1', name: 'Slack support', appearance: { deploymentChannel: 'slack' } }, { id: 'wrong-agent', name: 'Website support', appearance: { deploymentChannel: 'website' } }]);
  mocks.create.mockResolvedValue(saved); mocks.update.mockResolvedValue(saved); mocks.test.mockResolvedValue({ status: 'healthy' });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.clearAllMocks(); });

describe('integration catalogue and real setup', () => {
  it('puts CRM first and filters by category and search', async () => {
    render(<MemoryRouter><IntegrationsHubPage /></MemoryRouter>);
    expect(screen.getAllByRole('region')[0]).toHaveAccessibleName('CRM integrations');
    await userEvent.click(screen.getByRole('button', { name: 'Channels' }));
    expect(screen.queryByRole('heading', { name: 'Zoho CRM' })).not.toBeInTheDocument();
    await userEvent.type(screen.getByRole('textbox', { name: 'Search integrations' }), 'slack');
    expect(screen.getByRole('heading', { name: 'Slack' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Telegram' })).not.toBeInTheDocument();
    await userEvent.clear(screen.getByRole('textbox', { name: 'Search integrations' }));
    await userEvent.type(screen.getByRole('textbox', { name: 'Search integrations' }), 'unavailable-platform');
    expect(screen.getByText('No integrations found')).toBeInTheDocument();
  });

  it('collects Slack details, validates them and shows remaining webhook setup', async () => {
    const dialog = await open('Slack');
    expect(within(dialog).queryByRole('option', { name: 'Website support' })).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save and verify' }));
    expect(mocks.create).not.toHaveBeenCalled();
    await userEvent.selectOptions(within(dialog).getByLabelText('Agent'), 'agent-1');
    await userEvent.type(within(dialog).getByLabelText('Bot user OAuth token'), 'xoxb-private');
    await userEvent.type(within(dialog).getByLabelText('Signing secret'), 'private-signing');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save and verify' }));
    await screen.findByText('Finish message setup');
    expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({ provider: 'slack', agentId: 'agent-1', credentials: { bot_token: 'xoxb-private', signing_secret: 'private-signing' } }));
    expect(mocks.test).toHaveBeenCalledWith('slack-1');
    expect(screen.queryByDisplayValue('xoxb-private')).not.toBeInTheDocument();
    expect((screen.getByLabelText('Webhook URL') as HTMLInputElement).value).toContain('/webhooks/channels/tenant/slack/channel-1');
    expect(screen.queryByText('Connected', { exact: true })).not.toBeInTheDocument();
  });

  it('does not show success for rejected credentials and retries the same connection', async () => {
    mocks.test.mockResolvedValueOnce({ status: 'auth_required' });
    const dialog = await open('Slack');
    await userEvent.selectOptions(within(dialog).getByLabelText('Agent'), 'agent-1');
    await userEvent.type(within(dialog).getByLabelText('Bot user OAuth token'), 'bad-token');
    await userEvent.type(within(dialog).getByLabelText('Signing secret'), 'bad-secret');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save and verify' }));
    await screen.findByText(/Credentials could not be verified/);
    expect(screen.queryByText('Finish message setup')).not.toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText('Bot user OAuth token'), 'correct-token');
    await userEvent.type(within(dialog).getByLabelText('Signing secret'), 'correct-secret');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save and verify' }));
    await screen.findByText('Finish message setup');
    expect(mocks.create).toHaveBeenCalledTimes(1);
    expect(mocks.update).toHaveBeenCalledWith('slack-1', expect.objectContaining({ credentials: { bot_token: 'correct-token', signing_secret: 'correct-secret' } }));
  });

  it('uses platform-managed Zoho authorization without customer OAuth secrets', async () => {
    mocks.zohoStart.mockRejectedValueOnce(new Error('Zoho authorization is temporarily unavailable'));
    render(<MemoryRouter><IntegrationsHubPage /></MemoryRouter>);
    await userEvent.click(await screen.findByRole('button', { name: 'Connect Zoho CRM' }));
    const connect = await screen.findByRole('button', { name: 'Connect Zoho' });
    expect(screen.queryByLabelText('Client secret')).not.toBeInTheDocument();
    await userEvent.click(connect);
    await waitFor(() => expect(mocks.zohoStart).toHaveBeenCalledOnce());
    expect(await screen.findByRole('alert')).toHaveTextContent('Zoho authorization is temporarily unavailable');
    expect(mocks.start).not.toHaveBeenCalled();
  });

  it('prevents a viewer from connecting platforms', async () => {
    mocks.role = 'viewer';
    render(<MemoryRouter><IntegrationsHubPage /></MemoryRouter>);
    await waitFor(() => expect(screen.queryByText('Refreshing connection status…')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Connect Zoho CRM' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Connect Slack' })).toBeDisabled();
  });

  it('disables Zoho connection when the platform OAuth application is unconfigured', async () => {
    mocks.zohoStatus.mockResolvedValueOnce({ platformConfigured: false, connected: false, status: 'configuration_error', autoSyncNewLeads: false, autoSyncUpdates: false, mappingReady: false, routeReady: false, missingConfiguration: ['client ID'] });
    render(<MemoryRouter><IntegrationsHubPage /></MemoryRouter>);
    await userEvent.click(await screen.findByRole('button', { name: 'Connect Zoho CRM' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('platform Zoho OAuth application');
    expect(screen.getByRole('button', { name: 'Connect Zoho' })).toBeDisabled();
    expect(screen.queryByLabelText('Client secret')).not.toBeInTheDocument();
    expect(mocks.zohoStart).not.toHaveBeenCalled();
  });
});


it('offers reconnect through the existing one-click Zoho connection', async () => {
  mocks.crm.mockResolvedValue([{ id: 'zoho-existing', provider: 'zoho', name: 'Zoho CRM', status: 'degraded', environment: 'production' }]);
  mocks.zohoStatus.mockResolvedValueOnce({ platformConfigured: true, connected: true, status: 'degraded', connectionId: 'zoho-existing', autoSyncNewLeads: true, autoSyncUpdates: true, mappingReady: true, routeReady: true, missingConfiguration: [] });
  mocks.zohoStart.mockRejectedValueOnce(new Error('Reconnect temporarily unavailable'));
  render(<MemoryRouter><IntegrationsHubPage /></MemoryRouter>);
  await userEvent.click(await screen.findByRole('button', { name: 'Manage Zoho CRM' }));
  const reconnect = await screen.findByRole('button', { name: 'Reconnect Zoho' });
  await userEvent.click(reconnect);
  await waitFor(() => expect(mocks.zohoStart).toHaveBeenCalledOnce());
  expect(mocks.start).not.toHaveBeenCalled();
  expect(await screen.findByRole('alert')).toHaveTextContent('Reconnect temporarily unavailable');
});
