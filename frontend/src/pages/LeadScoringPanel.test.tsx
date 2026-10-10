import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LeadScoringPanel } from './LeadScoringPanel';
import type { CRMWorkflowJourney } from '@/lib/crm-workflow-api';

const mocks = vi.hoisted(() => ({
  policy: vi.fn(),
  savePolicy: vi.fn(),
  preview: vi.fn(),
  apply: vi.fn(),
}));
vi.mock('@/lib/crm-workflow-api', () => ({
  leadScoringApi: {
    policy: mocks.policy, savePolicy: mocks.savePolicy,
    preview: mocks.preview, apply: mocks.apply,
  },
}));

const journeys = [{
  leadId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  customerName: 'New lead', sourceChannel: 'widget',
} as CRMWorkflowJourney];

const defaultPolicy = {
  version: 1, enabled: true, base_points: 10,
  review_threshold: 40,
  rules: [{ field: 'source_channel', equals: 'widget', points: 35 }],
};

describe('CRM lead-scoring panel', () => {
  beforeEach(() => {
    mocks.policy.mockResolvedValue(defaultPolicy);
    mocks.savePolicy.mockImplementation(async (policy) => ({ ...policy, version: policy.version + 1 }));
    mocks.preview.mockResolvedValue({
      lead_id: journeys[0]!.leadId,
      policy_version: 1, eligible: true,
      ineligible_reason: null, current_score: 0, proposed_score: 45,
      review_threshold: 40, recommendation: 'review',
      qualification_status: 'pending',
      rules: [{ field: 'source_channel', equals: 'widget', points: 35, matched: true }],
    });
    mocks.apply.mockImplementation(async (_, preview) => ({
      ...preview, current_score: preview.proposed_score,
    }));
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.restoreAllMocks();
  });

  it('saves a version-guarded policy without triggering lead scoring or messaging', async () => {
    render(<LeadScoringPanel journeys={journeys} onApplied={vi.fn()}/>);
    const startingScore = await screen.findByLabelText('Starting score (0–100)');
    fireEvent.change(startingScore, { target: { value: '20' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save policy' }));
    await waitFor(() => expect(mocks.savePolicy).toHaveBeenCalledTimes(1));
    expect(mocks.savePolicy.mock.calls[0]![0]).toMatchObject({
      version: 1, enabled: true, base_points: 20, review_threshold: 40,
    });
    expect(mocks.preview).not.toHaveBeenCalled();
    expect(mocks.apply).not.toHaveBeenCalled();
    expect(await screen.findByText(/policy saved as version 2/i)).toBeInTheDocument();
  });

  it('separates preview from explicit human-approved score application', async () => {
    const applied = vi.fn();
    render(<LeadScoringPanel journeys={journeys} onApplied={applied}/>);
    const selector = await screen.findByLabelText('Lead');
    fireEvent.change(selector, { target: { value: journeys[0]!.leadId } });
    fireEvent.click(screen.getByRole('button', { name: 'Preview score' }));
    expect(await screen.findByText(/Suggested score: 45\/100/)).toBeInTheDocument();
    expect(screen.getByText(/Current qualification: pending/)).toBeInTheDocument();
    expect(mocks.apply).not.toHaveBeenCalled();

    vi.spyOn(window, 'confirm').mockReturnValue(true);
    fireEvent.click(screen.getByRole('button', { name: 'Apply explained score' }));
    await waitFor(() => expect(mocks.apply).toHaveBeenCalledTimes(1));
    expect(mocks.apply.mock.calls[0]![0]).toBe(journeys[0]!.leadId);
    expect(mocks.apply.mock.calls[0]![1]).toMatchObject({
      policy_version: 1, current_score: 0, proposed_score: 45,
    });
    expect(applied).toHaveBeenCalledTimes(1);
    expect(await screen.findByText(/score saved with an actor-attributed audit event/i)).toBeInTheDocument();
  });

  it('blocks application when consent or policy forbids scoring', async () => {
    mocks.preview.mockResolvedValueOnce({
      lead_id: journeys[0]!.leadId,
      policy_version: 1, eligible: false,
      ineligible_reason: 'Required processing consent is missing or withdrawn',
      current_score: 0, proposed_score: null,
      review_threshold: 40, recommendation: 'blocked',
      qualification_status: 'pending', rules: [],
    });
    render(<LeadScoringPanel journeys={journeys} onApplied={vi.fn()}/>);
    const selector = await screen.findByLabelText('Lead');
    fireEvent.change(selector, { target: { value: journeys[0]!.leadId } });
    fireEvent.click(screen.getByRole('button', { name: 'Preview score' }));
    expect(await screen.findByText(/Required processing consent is missing or withdrawn/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Apply explained score' })).toBeDisabled();
    expect(mocks.apply).not.toHaveBeenCalled();
  });
});
