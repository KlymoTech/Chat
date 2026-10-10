import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CRMInternalAutomationsPanel } from './CRMInternalAutomationsPanel';

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  save: vi.fn(),
  preview: vi.fn(),
  execute: vi.fn(),
  segments: vi.fn(),
}));
vi.mock('@/lib/crm-workflow-api', () => ({
  internalAutomationsApi: {
    list: mocks.list,
    save: mocks.save,
    preview: mocks.preview,
    execute: mocks.execute,
  },
  leadSegmentsApi: { list: mocks.segments },
}));

const automationId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const segmentId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const validAutomation = {
  id: automationId, name: 'Review new enquiries',
  segment_id: segmentId, enabled: true,
  action: 'notify_admins' as const, max_per_run: 5,
};
const savedRegister = { version: 2, automations: [validAutomation] };
const simulation = {
  automationId, policyVersion: 2, segmentVersion: 4,
  eligibleLeads: 3, eligibleFingerprint: 'a'.repeat(64),
  alreadyQueued: 1, remainingEligible: 2,
  blockedByConsentOrStatus: 4, unknownInputLeads: 1,
  examinedLeads: 9, truncated: false, maxPerRun: 5,
  action: 'notify_admins' as const, externalDelivery: false as const,
  note: 'Simulation only. No lead was contacted.',
};

describe('Internal Lead automations inside existing CRM Workflow', () => {
  beforeEach(() => {
    mocks.list.mockResolvedValue(structuredClone(savedRegister));
    mocks.segments.mockResolvedValue({
      version: 4,
      segments: [
        { id: segmentId, name: 'New enquiries', purpose: 'operations', enabled: true },
        { id: 'marketing-only', name: 'Marketing customers', purpose: 'marketing', enabled: true },
        { id: 'disabled-operations', name: 'Disabled', purpose: 'operations', enabled: false },
      ],
    });
    mocks.save.mockImplementation(async (draft) => ({
      ...structuredClone(draft), version: draft.version + 1,
    }));
    mocks.preview.mockResolvedValue(structuredClone(simulation));
    mocks.execute.mockResolvedValue({
      automationId, policyVersion: 2, queuedReviews: 2,
      previouslyQueued: 1, noRecipients: 0, remainingEligible: 0,
      externalDelivery: false, note: 'Internal review only.',
    });
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); vi.restoreAllMocks(); });

  it('loads existing definitions and never changes a Lead before deliberate action', async () => {
    render(<CRMInternalAutomationsPanel />);
    const picker = await screen.findByLabelText('Automation');
    await waitFor(() => expect(picker).toHaveValue(automationId));
    expect(screen.getByLabelText('Enabled operational segment')).toHaveValue(segmentId);
    expect(screen.queryByRole('option', { name: /Marketing customers/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /Disabled/ })).not.toBeInTheDocument();
    expect(mocks.save).not.toHaveBeenCalled();
    expect(mocks.preview).not.toHaveBeenCalled();
    expect(mocks.execute).not.toHaveBeenCalled();
  });

  it('saves a versioned policy but never executes or contacts customers', async () => {
    render(<CRMInternalAutomationsPanel />);
    const name = await screen.findByLabelText('Automation name');
    fireEvent.change(name, { target: { value: 'Qualified admissions review' } });
    expect(screen.getByRole('button', { name: 'Simulate without changes' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Save automation rules' }));
    await waitFor(() => expect(mocks.save).toHaveBeenCalledTimes(1));
    expect(mocks.save.mock.calls[0]![0]).toMatchObject({
      version: 2,
      automations: [{
        id: automationId, name: 'Qualified admissions review',
        segment_id: segmentId, enabled: true,
        action: 'notify_admins', max_per_run: 5,
      }],
    });
    expect(mocks.preview).not.toHaveBeenCalled();
    expect(mocks.execute).not.toHaveBeenCalled();
    expect(await screen.findByText(/definitions saved as version 3/)).toBeInTheDocument();
  });

  it('requires fresh simulation and explicit confirmation before queuing internal reviews', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<CRMInternalAutomationsPanel />);
    const simulate = await screen.findByRole('button', { name: 'Simulate without changes' });
    fireEvent.click(simulate);
    expect(await screen.findByText('Read-only simulation')).toBeInTheDocument();
    expect(screen.getByText(/Consent\/status blocked: 4/)).toBeInTheDocument();
    expect(mocks.execute).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm and queue internal reviews' }));
    expect(confirm).toHaveBeenCalledOnce();
    expect(mocks.execute).not.toHaveBeenCalled();

    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole('button', { name: 'Confirm and queue internal reviews' }));
    await waitFor(() => expect(mocks.execute).toHaveBeenCalledTimes(1));
    expect(mocks.execute).toHaveBeenCalledWith(automationId, simulation);
    expect(await screen.findByText(/2 internal lead reviews queued/)).toBeInTheDocument();
    expect(screen.getByText(/No customers were contacted/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Confirm and queue internal reviews' })).not.toBeInTheDocument();
  });

  it('blocks execution of truncated simulations even with matching segments', async () => {
    mocks.preview.mockResolvedValueOnce({ ...simulation, truncated: true, remainingEligible: 2 });
    render(<CRMInternalAutomationsPanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'Simulate without changes' }));
    expect(await screen.findByText('Safety limit exceeded')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Confirm and queue internal reviews' })).toBeDisabled();
    expect(mocks.execute).not.toHaveBeenCalled();
  });

  it('keeps an unsaved policy when the server rejects a version conflict', async () => {
    mocks.save.mockRejectedValueOnce(new Error('Automations changed; reload before saving'));
    render(<CRMInternalAutomationsPanel />);
    const input = await screen.findByLabelText('Automation name');
    fireEvent.change(input, { target: { value: 'Unsent operations review' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save automation rules' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Automations changed');
    expect(input).toHaveValue('Unsent operations review');
    expect(mocks.execute).not.toHaveBeenCalled();
  });
});
