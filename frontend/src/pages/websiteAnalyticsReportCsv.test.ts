import { describe, expect, it } from 'vitest';
import {
  reportCsvFilename,
  websiteAnalyticsReportCsv,
  type WebsiteDailyReport,
} from './websiteAnalyticsReportCsv';

const zero = {
  pageViews: 0, ctaClicks: 0, acceptedForms: 0,
  eventsPublishedToBroker: 0, eventsQueued: 0, eventsRetrying: 0,
  missingOutboxEvents: 0,
};
const fixture: WebsiteDailyReport = {
  days: 2, timezone: 'UTC',
  windowStart: '2026-10-09T00:00:00+00:00',
  windowEnd: '2026-10-10T09:00:00+00:00',
  daily: [
    { date: '2026-10-09', ...zero, pageViews: 2, acceptedForms: 1, eventsQueued: 1 },
    { date: '2026-10-10', ...zero, pageViews: 5, ctaClicks: 3, acceptedForms: 1, eventsRetrying: 1 },
  ],
  totals: {
    ...zero, pageViews: 7, ctaClicks: 3,
    acceptedForms: 2, eventsQueued: 1, eventsRetrying: 1,
  },
  deliveryConfirmed: false,
  reconciliationNote: 'Broker publication is not confirmed CRM delivery.',
  privacyNote: 'No personal data is included.',
};

describe('permission-safe analytics CSV generation', () => {
  it('exports only daily aggregate columns and a totals row', () => {
    const csv = websiteAnalyticsReportCsv(fixture);
    expect(csv.split('\r\n').filter(Boolean)).toHaveLength(4);
    expect(csv).toContain('"UTC date","Consented page views"');
    expect(csv).toContain('"2026-10-09","2","0","1","0","1","0","0"');
    expect(csv).toContain('"TOTAL","7","3","2","0","1","1","0"');
    expect(csv).not.toContain('visitorHash');
    expect(csv).not.toContain('leadId');
    expect(csv).not.toContain('email');
    expect(reportCsvFilename(fixture)).toBe('website-analytics-2026-10-10-2d.csv');
  });

  it('protects CSV cells from spreadsheet-formula interpretation', () => {
    const malformed = {
      ...fixture,
      daily: [{ ...fixture.daily[0]!, date: '=HYPERLINK("https://example.org")' }],
    };
    const csv = websiteAnalyticsReportCsv(malformed);
    expect(csv).toContain(`"'=HYPERLINK(""https://example.org"")"`);
  });
});
