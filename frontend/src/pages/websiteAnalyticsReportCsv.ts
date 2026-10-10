/** Canonical first-party analytics report contract; aggregate counts only. */
export interface WebsiteDailyRow {
  date: string;
  pageViews: number;
  ctaClicks: number;
  acceptedForms: number;
  eventsPublishedToBroker: number;
  eventsQueued: number;
  eventsRetrying: number;
  missingOutboxEvents: number;
}

export interface WebsiteDailyReport {
  days: number;
  timezone: 'UTC';
  windowStart: string;
  windowEnd: string;
  daily: WebsiteDailyRow[];
  totals: Omit<WebsiteDailyRow, 'date'>;
  deliveryConfirmed: false;
  reconciliationNote: string;
  privacyNote: string;
}

const columns: Array<{ key: keyof WebsiteDailyRow; label: string }> = [
  { key: 'date', label: 'UTC date' },
  { key: 'pageViews', label: 'Consented page views' },
  { key: 'ctaClicks', label: 'Consented CTA clicks' },
  { key: 'acceptedForms', label: 'Committed form receipts' },
  { key: 'eventsPublishedToBroker', label: 'Published to event broker' },
  { key: 'eventsQueued', label: 'Queued events' },
  { key: 'eventsRetrying', label: 'Retrying events' },
  { key: 'missingOutboxEvents', label: 'Unmatched receipts' },
];

/** CSV has no direct visitor data, and guards spreadsheet formula injection. */
function cell(value: string | number): string {
  let text = String(value);
  if (/^[\s]*[=+\-@]/.test(text) || /^[\t\r\n]/.test(text)) {
    text = "'" + text;
  }
  return '"' + text.replaceAll('"', '""') + '"';
}

export function websiteAnalyticsReportCsv(report: WebsiteDailyReport): string {
  const headers = columns.map((column) => cell(column.label)).join(',');
  const rows = report.daily.map((row) => columns.map((column) => cell(row[column.key])).join(','));
  const totals = columns.map((column) =>
    cell(column.key === 'date' ? 'TOTAL' : report.totals[column.key] ?? 0),
  ).join(',');
  // Notes are constant backend-generated descriptions, not user supplied.
  // Keep notes outside the CSV to avoid accidental spreadsheet execution.
  return [headers, ...rows, totals].join('\r\n') + '\r\n';
}

export function reportCsvFilename(report: WebsiteDailyReport): string {
  const day = report.windowEnd.slice(0, 10).replace(/[^0-9-]/g, '');
  return 'website-analytics-' + day + '-' + report.days + 'd.csv';
}
