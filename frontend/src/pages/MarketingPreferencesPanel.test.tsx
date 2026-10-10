import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MarketingPreferencesPanel } from './MarketingPreferencesPanel';
import type { CRMWorkflowJourney } from '@/lib/crm-workflow-api';

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  withdraw: vi.fn(),
  createUnsubscribeLink: vi.fn(),
  publicUrl: vi.fn(),
}));

vi.mock('@/lib/crm-workflow-api', () => ({
  marketingPreferencesApi: {
    get: mocks.get,
    withdraw: mocks.withdraw,
    createUnsubscribeLink: mocks.createUnsubscribeLink,
    publicUrl: mocks.publicUrl,
  },
}));

const leadId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const journeys = [{
  leadId, customerName: 'First-party enquiry', sourceChannel: 'website_form',
} as CRMWorkflowJourney];

describe('marketing consent and suppression panel', () => {
  beforeEach(() => {
    mocks.get.mockResolvedValue({
      leadId, marketingStatus: 'granted', marketingAllowed: true,
      processingConsentPreserved: true,
      note: 'Purpose-specific consent',
    });
    mocks.withdraw.mockResolvedValue({
      status: 'withdrawn', changed: true, processingConsentPreserved: true,
    });
    mocks.createUnsubscribeLink.mockResolvedValue({
      path: '/api/v1/site-marketing/unsubscribe/opaque-signed-link',
      expiresIn: '30 days', note: 'Confidential bearer link',
    });
    mocks.publicUrl.mockReturnValue(
      'https://website.example/api/v1/site-marketing/unsubscribe/opaque-signed-link',
    );
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); vi.restoreAllMocks(); });

  it('does not request or change marketing data until a lead is deliberately selected', async () => {
    render(<MarketingPreferencesPanel journeys={journeys}/>);
    expect(mocks.get).not.toHaveBeenCalled();
    expect(mocks.withdraw).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Lead'), { target: { value: leadId } });
    expect(mocks.get).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Check permission' }));
    expect(await screen.findByText('granted')).toBeInTheDocument();
    expect(screen.getByText(/Enquiry-processing permission is not modified/)).toBeInTheDocument();
    expect(mocks.withdraw).not.toHaveBeenCalled();
  });

  it('needs explicit owner confirmation, then refreshes the consent-specific status', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<MarketingPreferencesPanel journeys={journeys}/>);
    fireEvent.change(screen.getByLabelText('Lead'), { target: { value: leadId } });
    fireEvent.click(screen.getByRole('button', { name: 'Check permission' }));
    await screen.findByText('granted');
    fireEvent.click(screen.getByRole('button', { name: 'Withdraw marketing permission' }));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(mocks.withdraw).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    mocks.get.mockResolvedValueOnce({
      leadId, marketingStatus: 'withdrawn', marketingAllowed: false,
      processingConsentPreserved: true, note: 'Purpose-specific consent',
    });
    fireEvent.click(screen.getByRole('button', { name: 'Withdraw marketing permission' }));
    await waitFor(() => expect(mocks.withdraw).toHaveBeenCalledTimes(1));
    expect(mocks.withdraw).toHaveBeenCalledWith(leadId);
    expect(await screen.findByText('withdrawn')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Withdraw marketing permission' })).toBeDisabled();
  });

  it('does not issue a signed link until requested and keeps it ephemeral', async () => {
    render(<MarketingPreferencesPanel journeys={journeys}/>);
    fireEvent.change(screen.getByLabelText('Lead'), { target: { value: leadId } });
    fireEvent.click(screen.getByRole('button', { name: 'Check permission' }));
    await screen.findByText('granted');
    expect(mocks.createUnsubscribeLink).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Create unsubscribe link' }));
    const value = await screen.findByDisplayValue(
      'https://website.example/api/v1/site-marketing/unsubscribe/opaque-signed-link',
    );
    expect(value).toBeInTheDocument();
    expect(mocks.createUnsubscribeLink).toHaveBeenCalledWith(leadId);
    fireEvent.change(screen.getByLabelText('Lead'), { target: { value: '' } });
    expect(screen.queryByDisplayValue(/opaque-signed-link/)).not.toBeInTheDocument();
  });

  it('does not treat unknown marketing permission as authorization', async () => {
    mocks.get.mockResolvedValueOnce({
      leadId, marketingStatus: 'unknown', marketingAllowed: false,
      processingConsentPreserved: true, note: 'No marketing grant',
    });
    render(<MarketingPreferencesPanel journeys={journeys}/>);
    fireEvent.change(screen.getByLabelText('Lead'), { target: { value: leadId } });
    fireEvent.click(screen.getByRole('button', { name: 'Check permission' }));
    expect(await screen.findByText('unknown')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Withdraw marketing permission' })).toBeEnabled();
    expect(mocks.withdraw).not.toHaveBeenCalled();
  });
});
