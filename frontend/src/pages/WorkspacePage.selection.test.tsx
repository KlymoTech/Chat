/* @vitest-environment jsdom */
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { WorkspacePage } from '@/pages/WorkspacePage';
import type { WorkspaceSettings } from '@/lib/workspace-api';

const mocks = vi.hoisted(() => ({
  get: vi.fn(), update: vi.fn(), pushToast: vi.fn(), activeId: 'workspace-alpha',
}));

vi.mock('@/lib/workspace-api', () => ({
  workspaceApi: { get: mocks.get, update: mocks.update },
  activeWorkspaceId: () => mocks.activeId,
  workspacePresentationKey: () => 'same-user-and-tenant',
  WORKSPACE_CHANGED_EVENT: 'northstar:active-workspace-changed',
}));
vi.mock('@/components/providers', () => ({
  useAuth: () => ({ session: { user: { name: 'Workspace Owner', email: 'owner@example.com' } } }),
  useToast: () => ({ pushToast: mocks.pushToast }),
}));
vi.mock('react-router-dom', () => ({
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
}));
vi.mock('@/components/mfa-security-panel', () => ({ MFASecurityPanel: () => null }));
vi.mock('@/components/SubscriptionBillingPanel', () => ({ SubscriptionBillingPanel: () => null }));
vi.mock('@/components/WorkspaceAPIKeysPanel', () => ({ WorkspaceAPIKeysPanel: () => null }));
vi.mock('@/components/workspace-navigation', () => ({ WorkspaceNavigation: () => null }));
vi.mock('@/components/WorkspaceTeamPanel', () => ({ WorkspaceTeamPanel: () => null }));

function fixture(id: string, name: string): WorkspaceSettings {
  return {
    id, name, slug: id, plan: 'business', memberCount: 1,
    permissions: ['workspace.view', 'workspace.update'],
    preferences: { timezone: 'UTC', defaultLanguage: 'English', dateFormat: 'DD/MM/YYYY' },
    security: { sensitiveDataMasking: true, securityContact: null },
    whiteLabel: {
      companyName: 'Example', logoDataUrl: '', faviconDataUrl: '', appIconDataUrl: '',
      primaryColor: '#0c0b0b', secondaryColor: '#6b6b70', supportEmail: null,
      supportUrl: '', browserTitle: 'Example', customDomain: '', dnsStatus: 'not-configured',
      brandedLogin: false, brandedDashboard: true, brandedWidget: false,
      brandedEmails: false, removePlatformBranding: false,
    },
  };
}

const alpha = fixture('workspace-alpha', 'Alpha Workspace');
const beta = fixture('workspace-beta', 'Beta Workspace');

beforeEach(() => {
  mocks.activeId = 'workspace-alpha';
  mocks.get.mockReset();
  mocks.update.mockReset();
  mocks.pushToast.mockReset();
});
afterEach(cleanup);

describe('WorkspacePage active selection isolation', () => {
  it('discards the old load response when the user switches workspaces', async () => {
    let resolveAlpha!: (workspace: WorkspaceSettings) => void;
    mocks.get.mockImplementationOnce(() => new Promise<WorkspaceSettings>((resolve) => { resolveAlpha = resolve; }));
    mocks.get.mockResolvedValueOnce(beta);
    render(<WorkspacePage />);
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(1));
    await act(async () => {
      mocks.activeId = beta.id;
      window.dispatchEvent(new CustomEvent('northstar:active-workspace-changed', { detail: beta.id }));
    });
    expect(await screen.findByDisplayValue(beta.name)).toBeInTheDocument();
    await act(async () => resolveAlpha(alpha));
    expect(screen.queryByDisplayValue(alpha.name)).not.toBeInTheDocument();
    expect(screen.getByDisplayValue(beta.name)).toBeInTheDocument();
  });

  it('does not render an old save result into the newly selected workspace', async () => {
    let resolveOldSave!: (workspace: WorkspaceSettings) => void;
    mocks.get.mockResolvedValueOnce(alpha).mockResolvedValueOnce(beta);
    mocks.update.mockImplementationOnce(() => new Promise<WorkspaceSettings>((resolve) => { resolveOldSave = resolve; }));
    render(<WorkspacePage />);
    expect(await screen.findByDisplayValue(alpha.name)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Save workspace' }));
    await waitFor(() => expect(mocks.update).toHaveBeenCalledTimes(1));
    await act(async () => {
      mocks.activeId = beta.id;
      window.dispatchEvent(new CustomEvent('northstar:active-workspace-changed', { detail: beta.id }));
    });
    expect(await screen.findByDisplayValue(beta.name)).toBeInTheDocument();
    await act(async () => resolveOldSave(alpha));
    expect(screen.getByDisplayValue(beta.name)).toBeInTheDocument();
    expect(mocks.pushToast).not.toHaveBeenCalledWith('Workspace settings saved');
  });
});
