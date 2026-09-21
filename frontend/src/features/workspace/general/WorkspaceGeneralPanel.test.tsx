/* @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { WorkspaceGeneralPanel } from '@/features/workspace/general/WorkspaceGeneralPanel';
import type { WorkspaceSettings } from '@/lib/workspace-api';

const workspace: WorkspaceSettings = {
  id: 'workspace-1', name: 'Northstar Workspace', slug: 'northstar',
  plan: 'business', memberCount: 1,
  preferences: { timezone: 'Asia/Calcutta', defaultLanguage: 'English', dateFormat: 'DD/MM/YYYY' },
  security: { sensitiveDataMasking: true, securityContact: null },
  whiteLabel: {
    companyName: 'Northstar AI', logoDataUrl: '', faviconDataUrl: '', appIconDataUrl: '',
    primaryColor: '#0c0b0b', secondaryColor: '#6b6b70', supportEmail: null, supportUrl: '',
    browserTitle: 'Northstar AI', customDomain: '', dnsStatus: 'not-configured',
    brandedLogin: false, brandedDashboard: true, brandedWidget: false,
    brandedEmails: false, removePlatformBranding: false,
  },
};

afterEach(cleanup);

describe('WorkspaceGeneralPanel', () => {
  it('preserves the existing profile fields and education guidance', () => {
    render(<WorkspaceGeneralPanel
      workspace={workspace}
      setWorkspace={vi.fn()}
      onSave={vi.fn()}
      saving={false}
      ownerInitial="N"
    />);

    expect(screen.getByRole('heading', { name: 'Workspace profile' })).toBeTruthy();
    expect(screen.getByLabelText('Workspace name')).toBeTruthy();
    expect(screen.getByLabelText('Workspace slug')).toBeTruthy();
    expect(screen.getByLabelText('Timezone')).toBeTruthy();
    expect(screen.getByLabelText('Date format')).toBeTruthy();
    expect(screen.getByLabelText('Default workspace language')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Education conversations' })).toBeTruthy();
  });

  it('updates the owned workspace state and invokes the existing save handler', () => {
    const setWorkspace = vi.fn();
    const onSave = vi.fn();
    render(<WorkspaceGeneralPanel
      workspace={workspace}
      setWorkspace={setWorkspace}
      onSave={onSave}
      saving={false}
      ownerInitial="N"
    />);

    fireEvent.change(screen.getByLabelText('Workspace name'), { target: { value: 'Updated workspace' } });
    expect(setWorkspace).toHaveBeenCalledWith(expect.objectContaining({ name: 'Updated workspace' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save workspace' }));
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it('disables saving during an active request', () => {
    render(<WorkspaceGeneralPanel
      workspace={workspace}
      setWorkspace={vi.fn()}
      onSave={vi.fn()}
      saving
      ownerInitial="N"
    />);
    expect((screen.getByRole('button', { name: 'Saving…' }) as HTMLButtonElement).disabled).toBe(true);
  });
});
