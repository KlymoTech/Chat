/* @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { WorkspaceGeneralPanel } from '@/features/workspace/general/WorkspaceGeneralPanel';
import type { WorkspaceSettings } from '@/lib/workspace-api';

const workspace: WorkspaceSettings = {
  id: 'workspace-1', name: 'Northstar Workspace', slug: 'northstar',
  plan: 'business', memberCount: 1, permissions: ['workspace.view', 'workspace.update'],
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
    render(<WorkspaceGeneralPanel workspace={workspace} setWorkspace={vi.fn()} onSave={vi.fn()} saving={false} ownerInitial="N" />);
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
    render(<WorkspaceGeneralPanel workspace={workspace} setWorkspace={setWorkspace} onSave={onSave} saving={false} ownerInitial="N" />);
    fireEvent.change(screen.getByLabelText('Workspace name'), { target: { value: 'Updated workspace' } });
    expect(setWorkspace).toHaveBeenCalledWith(expect.objectContaining({ name: 'Updated workspace' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save workspace' }));
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it('disables saving during an active request', () => {
    render(<WorkspaceGeneralPanel workspace={workspace} setWorkspace={vi.fn()} onSave={vi.fn()} saving ownerInitial="N" />);
    expect((screen.getByRole('button', { name: 'Saving…' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('prevents viewers from editing or submitting while retaining read access', () => {
    const setWorkspace = vi.fn();
    const onSave = vi.fn();
    render(<WorkspaceGeneralPanel
      workspace={{ ...workspace, role: 'viewer', permissions: ['workspace.view'] }}
      setWorkspace={setWorkspace} onSave={onSave} saving={false} ownerInitial="N"
    />);
    expect(screen.getByRole('status').textContent).toMatch(/only a workspace administrator/);
    expect((screen.getByLabelText('Workspace name') as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByLabelText('Workspace slug') as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByLabelText('Timezone') as HTMLSelectElement).disabled).toBe(true);
    expect((screen.getByLabelText('Default workspace language') as HTMLSelectElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Save workspace' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Save workspace' }));
    expect(setWorkspace).not.toHaveBeenCalled();
    expect(onSave).not.toHaveBeenCalled();
  });

  it('requires valid workspace names and slugs before submission', () => {
    render(<WorkspaceGeneralPanel workspace={workspace} setWorkspace={vi.fn()} onSave={vi.fn()} saving={false} ownerInitial="N" />);
    const name = screen.getByLabelText('Workspace name') as HTMLInputElement;
    const slug = screen.getByLabelText('Workspace slug') as HTMLInputElement;
    expect(name.minLength).toBe(2);
    expect(name.maxLength).toBe(160);
    expect(slug.maxLength).toBe(80);
    expect(slug.pattern).toBe('[a-z0-9]+(-[a-z0-9]+)*');
    expect(name.required && slug.required).toBe(true);
  });
});
