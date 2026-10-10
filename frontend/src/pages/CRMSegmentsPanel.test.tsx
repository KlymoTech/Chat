import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CRMSegmentsPanel } from './CRMSegmentsPanel';

const mocks = vi.hoisted(() => ({
  list: vi.fn(), save: vi.fn(), preview: vi.fn(),
}));
vi.mock('@/lib/crm-workflow-api', () => ({
  leadSegmentsApi: { list: mocks.list, save: mocks.save, preview: mocks.preview },
}));

const base = { version: 0, segments: [] };
const draftSegment = {
  id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  name: 'Website enquiries',
  enabled: true, purpose: 'marketing', logic: 'all',
  include: [{ field: 'source_channel', equals: 'website_form' }],
  exclude: [],
};

describe('CRM segment editor', () => {
  beforeEach(() => {
    mocks.list.mockResolvedValue(structuredClone(base));
    mocks.save.mockImplementation(async (request) => ({
      version: request.version + 1, segments: request.segments,
    }));
    mocks.preview.mockResolvedValue({
      segmentId: draftSegment.id, policyVersion: 1,
      purpose: 'marketing', enabled: true,
      matchedLeads: 2, blockedByEligibility: 10,
      unknownInputLeads: 1, examinedLeads: 13,
      truncated: true, exactCount: false,
      evaluatedAt: '2026-10-10T09:00:00Z',
      note: 'No contacts were exported or messaged.',
    });
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); vi.restoreAllMocks(); });

  it('saves bounded rules with the existing workspace version and no sends', async () => {
    render(<CRMSegmentsPanel />);
    await screen.findByText('Consent-aware Lead segments');
    fireEvent.click(screen.getByRole('button', { name: 'Create segment' }));
    fireEvent.change(screen.getByLabelText('Segment name'), {
      target: { value: 'Internal operations review' },
    });
    expect(screen.getByRole('button', { name: 'Save definitions' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Save definitions' }));
    await waitFor(() => expect(mocks.save).toHaveBeenCalledTimes(1));
    expect(mocks.save.mock.calls[0]![0]).toMatchObject({
      version: 0,
      segments: [{
        name: 'Internal operations review',
        purpose: 'operations',
        include: [{ field: 'source_channel', equals: 'website_form' }],
      }],
    });
    expect(mocks.preview).not.toHaveBeenCalled();
    expect(await screen.findByText(/saved as workspace version 1/)).toBeInTheDocument();
  });

  it('previews marketing audiences with eligibility exclusions and truncation warnings', async () => {
    mocks.list.mockResolvedValueOnce({ version: 1, segments: [draftSegment] });
    render(<CRMSegmentsPanel />);
    await screen.findByText('Consent-aware Lead segments');
    expect(await screen.findByLabelText('Authorized purpose')).toHaveValue('marketing');
    fireEvent.click(screen.getByRole('button', { name: 'Preview eligible count' }));
    const panel = await screen.findByRole('region', { name: 'Segment population preview' });
    expect(panel).toHaveTextContent('Rule matches and eligible');
    expect(panel).toHaveTextContent('Consent/status excluded');
    expect(panel).toHaveTextContent('Unknown rule inputs');
    expect(panel).toHaveTextContent('No contacts were exported or messaged');
    expect(panel).toHaveTextContent('Preview limit reached.');
    expect(mocks.preview).toHaveBeenCalledWith(draftSegment.id);
    expect(mocks.save).not.toHaveBeenCalled();
  });

  it('does not preview unsaved edits until policy is committed', async () => {
    mocks.list.mockResolvedValueOnce({ version: 1, segments: [draftSegment] });
    render(<CRMSegmentsPanel />);
    const name = await screen.findByLabelText('Segment name');
    fireEvent.change(name, { target: { value: 'Draft audience' } });
    expect(screen.getByRole('button', { name: 'Preview eligible count' })).toBeDisabled();
    expect(mocks.preview).not.toHaveBeenCalled();
  });
});
