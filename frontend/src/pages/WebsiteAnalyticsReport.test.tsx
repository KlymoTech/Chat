import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { WebsiteAnalyticsReport } from './WebsiteAnalyticsReport';

const mocks = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock('@/lib/api', () => ({ request: mocks.request }));

const daily = Array.from({ length: 30 }, (_, index) => ({
  date: '2026-09-' + String(index + 1).padStart(2, '0'),
  pageViews: index === 29 ? 5 : 0,
  ctaClicks: index === 29 ? 2 : 0,
  acceptedForms: index === 29 ? 2 : 0,
  eventsPublishedToBroker: index === 29 ? 1 : 0,
  eventsQueued: 0, eventsRetrying: 0,
  missingOutboxEvents: index === 29 ? 1 : 0,
}));
const report = {
  days: 30, timezone: 'UTC',
  windowStart: '2026-09-01T00:00:00+00:00',
  windowEnd: '2026-09-30T11:00:00+00:00',
  daily, deliveryConfirmed: false,
  totals: {
    pageViews: 5, ctaClicks: 2, acceptedForms: 2,
    eventsPublishedToBroker: 1, eventsQueued: 0, eventsRetrying: 0,
    missingOutboxEvents: 1,
  },
  reconciliationNote: 'Event-bus publication is not confirmed CRM delivery.',
  privacyNote: 'Only aggregated consented web events are shown.',
};

describe('existing CMS daily website report', () => {
  beforeEach(() => {
    mocks.request.mockResolvedValue(report);
  });
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('only requests data on demand and surfaces unmatched receipts', async () => {
    render(<WebsiteAnalyticsReport />);
    expect(mocks.request).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Download CSV' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Generate report' }));
    await waitFor(() => expect(mocks.request).toHaveBeenCalledWith(
      '/site-analytics/report?days=30',
    ));
    expect(await screen.findByText(/Reconciliation requires investigation/)).toBeInTheDocument();
    expect(screen.getByText(/Not a production delivery confirmation/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Download CSV' })).toBeEnabled();
    expect(screen.getByRole('table')).toBeInTheDocument();
  });

  it('does not expose stale data after changing reporting period', async () => {
    render(<WebsiteAnalyticsReport />);
    fireEvent.click(screen.getByRole('button', { name: 'Generate report' }));
    await screen.findByText(/Reconciliation requires investigation/);
    fireEvent.change(screen.getByLabelText('Period'), { target: { value: '7' } });
    expect(screen.getByRole('button', { name: 'Download CSV' })).toBeDisabled();
    expect(screen.queryByText(/Reconciliation requires investigation/)).not.toBeInTheDocument();
    mocks.request.mockResolvedValueOnce({
      ...report,
      days: 7,
      daily: report.daily.slice(-7),
    });
    fireEvent.click(screen.getByRole('button', { name: 'Generate report' }));
    await waitFor(() => expect(mocks.request).toHaveBeenCalledWith(
      '/site-analytics/report?days=7',
    ));
  });

  it('fails closed when the API contract is unsafe or unavailable', async () => {
    mocks.request.mockResolvedValueOnce({ ...report, deliveryConfirmed: true });
    render(<WebsiteAnalyticsReport />);
    fireEvent.click(screen.getByRole('button', { name: 'Generate report' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'unexpected data contract',
    );
    expect(screen.getByRole('button', { name: 'Download CSV' })).toBeDisabled();
  });
});
