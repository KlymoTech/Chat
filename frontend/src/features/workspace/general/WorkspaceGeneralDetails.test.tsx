/* @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { WorkspaceGeneralDetails } from '@/features/workspace/general/WorkspaceGeneralDetails';
import type { WorkspaceSettings } from '@/lib/workspace-api';

const workspace: WorkspaceSettings = {
  id: 'workspace-1', tenantName: 'Example Organization', name: 'Support', slug: 'support',
  status: 'active', plan: 'business', memberCount: 1, permissions: ['workspace.update'],
  preferences: {
    timezone: 'UTC', defaultLanguage: 'English', dateFormat: 'DD/MM/YYYY',
    industry: '', country: '', description: '', timeFormat: '24h', currency: 'USD',
    weekStart: 'monday', workspaceIcon: '',
  },
  security: { sensitiveDataMasking: true, securityContact: null },
  whiteLabel: {
    companyName: 'Example Organization', logoDataUrl: '', faviconDataUrl: '', appIconDataUrl: '',
    primaryColor: '#0c0b0b', secondaryColor: '#6b6b70', supportEmail: null, supportUrl: '',
    browserTitle: 'Example', customDomain: '', dnsStatus: 'not-configured', brandedLogin: false,
    brandedDashboard: true, brandedWidget: false, brandedEmails: false, removePlatformBranding: false,
  },
};
afterEach(cleanup);

describe('WorkspaceGeneralDetails', () => {
  it('shows stored workspace identifiers as read-only and edits scoped profile values', () => {
    const setWorkspace = vi.fn();
    render(<WorkspaceGeneralDetails workspace={workspace} setWorkspace={setWorkspace} disabled={false} />);
    expect((screen.getByLabelText('Workspace ID') as HTMLInputElement).readOnly).toBe(true);
    expect(screen.getByDisplayValue('Example Organization')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Industry'), { target: { value: 'Education' } });
    const updater = setWorkspace.mock.calls[0]![0] as (value: WorkspaceSettings | null) => WorkspaceSettings | null;
    expect(updater(workspace)?.preferences.industry).toBe('Education');
    expect(updater({ ...workspace, id: 'another-workspace' })?.id).toBe('another-workspace');
  });

  it('edits weekly business hours through the same preferences save pipeline', () => {
    const setWorkspace = vi.fn();
    render(<WorkspaceGeneralDetails workspace={workspace} setWorkspace={setWorkspace} disabled={false} />);
    fireEvent.click(screen.getByText('Business hours'));
    fireEvent.click(screen.getByRole('checkbox', { name: 'sunday open' }));
    const updater = setWorkspace.mock.calls[0]![0] as (value: WorkspaceSettings | null) => WorkspaceSettings | null;
    expect(updater(workspace)?.preferences.businessHours?.sunday).toEqual({
      enabled: true, opens: '09:00', closes: '17:00',
    });
    expect(screen.getByText(/do not yet change channel routing/)).toBeInTheDocument();
  });

  it('disables all editable profile controls without hiding workspace metadata', () => {
    render(<WorkspaceGeneralDetails workspace={workspace} setWorkspace={vi.fn()} disabled />);
    expect((screen.getByLabelText('Industry') as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByLabelText('Workspace description') as HTMLTextAreaElement).disabled).toBe(true);
    expect((screen.getByLabelText('Currency code') as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByDisplayValue(workspace.id)).toBeInTheDocument();
  });
});
