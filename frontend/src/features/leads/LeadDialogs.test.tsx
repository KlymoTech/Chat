import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AddLeadDialog, AssignLeadDialog, FollowUpDialog, LeadStageDialog } from './LeadDialogs';
import { demoAgents, demoLeads } from '@/lib/demo-data';
import type { LeadWorkspace } from './leadWorkspaceApi';
const mocks = vi.hoisted(() => ({ options: vi.fn(), create: vi.fn(), stage: vi.fn(), assign: vi.fn(), schedule: vi.fn() }));
vi.mock('./leadWorkspaceApi', () => ({ leadWorkspaceApi: mocks }));
const close = vi.fn(); const saved = vi.fn();
const lead = { ...demoLeads[0]!, status: 'new' };
const workspace: LeadWorkspace = { lead, version: 3, assignment: null, followUps: [] };
beforeEach(() => {
  vi.clearAllMocks();
  mocks.options.mockResolvedValue([{ id: 'person-a', name: 'Riya Sharma', kind: 'person', role: 'member' }, { id: 'team-a', name: 'Sales team', kind: 'team', role: '' }]);
  mocks.assign.mockResolvedValue({ ...workspace, version: 4 });
  mocks.stage.mockResolvedValue({ ...lead, status: 'qualified' });
  mocks.schedule.mockResolvedValue({ ...workspace, version: 4 });
  mocks.create.mockResolvedValue(lead);
});
afterEach(cleanup);
describe('Exported lead workflow dialogs', () => {
  it('assigns only a selected real workspace candidate and includes the version and note', async () => {
    render(<AssignLeadDialog workspace={workspace} onClose={close} onSaved={saved} />);
    expect(screen.getByRole('button', { name: 'Assign lead' })).toBeDisabled();
    await userEvent.click(await screen.findByRole('radio', { name: /Riya Sharma/ }));
    await userEvent.type(screen.getByLabelText('Assignment note'), 'Requested a demonstration');
    await userEvent.click(screen.getByRole('button', { name: 'Assign to Riya Sharma' }));
    expect(mocks.assign).toHaveBeenCalledWith(lead.id, { version: 3, kind: 'person', targetId: 'person-a', note: 'Requested a demonstration' });
    await waitFor(() => expect(saved).toHaveBeenCalled());
  });
  it('clears the person selection when switching to teams and filters real candidates', async () => {
    render(<AssignLeadDialog workspace={workspace} onClose={close} onSaved={saved} />);
    await userEvent.click(await screen.findByRole('radio', { name: /Riya Sharma/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Team' }));
    expect(screen.queryByRole('radio', { name: /Riya/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Assign lead' })).toBeDisabled();
    await userEvent.click(screen.getByRole('radio', { name: /Sales team/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Assign to Sales team' }));
    expect(mocks.assign).toHaveBeenCalledWith(lead.id, expect.objectContaining({ kind: 'team', targetId: 'team-a' }));
  });
  it('shows a conflict without closing or treating it as a saved assignment', async () => {
    mocks.assign.mockRejectedValueOnce(new Error('This lead changed in another session. Refresh and try again.'));
    render(<AssignLeadDialog workspace={workspace} onClose={close} onSaved={saved} />);
    await userEvent.click(await screen.findByRole('radio', { name: /Riya/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Assign to Riya Sharma' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('another session');
    expect(saved).not.toHaveBeenCalled(); expect(close).not.toHaveBeenCalled();
  });
  it('preserves status changes through the domain API and records the supplied note', async () => {
    render(<LeadStageDialog lead={lead} onClose={close} onSaved={saved} />);
    expect(screen.getByRole('button', { name: 'Update status' })).toBeDisabled();
    await userEvent.click(screen.getByRole('radio', { name: /Qualified/ }));
    await userEvent.type(screen.getByLabelText('Reason / note'), 'Confirmed budget');
    await userEvent.click(screen.getByRole('button', { name: 'Update status' }));
    expect(mocks.stage).toHaveBeenCalledWith(lead.id, 'qualified', 'Confirmed budget');
  });
  it('saves a future UTC follow-up with a real owner, idempotency key and calendar reminder', async () => {
    render(<FollowUpDialog workspace={workspace} onClose={close} onSaved={saved} />);
    expect(screen.getByRole('button', { name: 'Schedule follow-up' })).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Follow-up title'), 'Product demo');
    await screen.findByRole('option', { name: /Riya/ });
    await userEvent.selectOptions(screen.getByLabelText('Assign follow-up to'), 'person:person-a');
    await userEvent.click(screen.getByRole('button', { name: 'Schedule follow-up' }));
    expect(mocks.schedule).toHaveBeenCalledWith(lead.id, expect.objectContaining({ id: expect.any(String), version: 3, kind: 'call', title: 'Product demo', assigneeKind: 'person', assigneeId: 'person-a', reminderMinutes: 30, dueAt: expect.stringMatching(/Z$/) }));
    const payload = mocks.schedule.mock.calls[0]![1];
    expect(Date.parse(payload.dueAt)).toBeGreaterThan(Date.now());
    expect(payload.timezone).toBeTruthy();
  });
  it('requires explicit consent when adding a contact and never defaults to opt-in', async () => {
    render(<AddLeadDialog agents={demoAgents} onClose={close} onSaved={saved} />);
    expect(screen.getByRole('checkbox')).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Add Lead' })).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Full name'), 'Example Prospect');
    await userEvent.selectOptions(screen.getByLabelText('Assigned AI agent'), demoAgents[0]!.id);
    await userEvent.click(screen.getByRole('button', { name: 'Add Lead' }));
    expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({ name: 'Example Prospect', consent: false }));
  });
});
