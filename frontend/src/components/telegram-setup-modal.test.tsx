import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TelegramSetupModal, trustedTelegramUrl } from './telegram-setup-modal';

const mocks = vi.hoisted(() => ({ connect: vi.fn(), test: vi.fn(), disconnect: vi.fn(), changed: vi.fn() }));
vi.mock('@/lib/api', () => ({ api: { agents: { list: vi.fn().mockResolvedValue([{ id: 'agent-1', name: 'Tutor', appearance: { deploymentChannel: 'telegram' } }]) } } }));
vi.mock('@/lib/lead-crm-api', () => ({ leadCrmApi: { connectTelegramBot: mocks.connect, testChannelConnection: mocks.test, disconnectTelegramConnection: mocks.disconnect } }));

function show() { return render(<MemoryRouter><TelegramSetupModal connections={[]} canManage onChanged={mocks.changed} onClose={() => {}} /></MemoryRouter>); }

describe('normal Telegram bot setup', () => {
  beforeEach(() => { vi.clearAllMocks(); mocks.connect.mockResolvedValue({ id: 'connection-1' }); mocks.test.mockResolvedValue({ status: 'healthy' }); mocks.disconnect.mockResolvedValue(undefined); });
  afterEach(() => cleanup());
  it('submits a normal BotFather token without displaying it afterwards', async () => {
    show();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Connect' })).toBeDisabled());
    await userEvent.type(screen.getByLabelText('BotFather token'), '123456:token-value');
    await userEvent.click(screen.getByRole('button', { name: 'Connect' }));
    expect(mocks.connect).toHaveBeenCalledWith({ agentId: 'agent-1', name: 'Telegram bot', botToken: '123456:token-value' });
    expect(mocks.changed).toHaveBeenCalled();
  });
  it('accepts only trusted public Telegram bot URLs', () => {
    expect(trustedTelegramUrl('https://t.me/tutor_bot')).toBe(true);
    expect(trustedTelegramUrl('https://t.me.evil.example/tutor_bot')).toBe(false);
  });
});
