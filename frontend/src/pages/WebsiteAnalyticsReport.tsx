import { useState } from 'react';
import { AlertTriangle, Download, RefreshCw } from 'lucide-react';
import { Button, Card } from '@/components/ui';
import { request } from '@/lib/api';
import {
  reportCsvFilename,
  websiteAnalyticsReportCsv,
  type WebsiteDailyReport,
} from './websiteAnalyticsReportCsv';
import './WebsiteAnalyticsReport.css';

/** Existing CMS owner reporting; no new analytics identity or lead store. */
export function WebsiteAnalyticsReport() {
  const [days, setDays] = useState<7 | 30 | 90>(30);
  const [report, setReport] = useState<WebsiteDailyReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    setReport(null);
    try {
      const data = await request<WebsiteDailyReport>('/site-analytics/report?days=' + days);
      if (data.timezone !== 'UTC' || data.deliveryConfirmed !== false ||
        data.daily.length !== days) {
        throw new Error('Analytics report returned an unexpected data contract.');
      }
      setReport(data);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Website reporting is unavailable.');
    } finally {
      setBusy(false);
    }
  };

  const download = () => {
    if (!report) return;
    const blob = new Blob(['\uFEFF', websiteAnalyticsReportCsv(report)],
      { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    try {
      link.href = url;
      link.download = reportCsvFilename(report);
      document.body.appendChild(link);
      link.click();
    } finally {
      link.remove();
      URL.revokeObjectURL(url);
    }
  };

  const totals = report?.totals;
  const hasExceptions = Boolean(
    totals && (totals.eventsRetrying > 0 || totals.missingOutboxEvents > 0),
  );
  const highestViews = Math.max(1, ...(report?.daily.map((row) => row.pageViews) ?? []));
  return <Card>
    <div className="site-report-heading">
      <div>
        <h3>Daily website reporting</h3>
        <p>UTC trends and reconciliation from the existing consented event collector and authoritative form receipts.</p>
      </div>
      <div className="site-report-actions">
        <label>Period
          <select value={days} disabled={busy} onChange={(event) => {
            setDays(Number(event.target.value) as 7 | 30 | 90);
            setReport(null);
            setError('');
          }}>
            <option value={7}>Last 7 UTC dates</option>
            <option value={30}>Last 30 UTC dates</option>
            <option value={90}>Last 90 UTC dates</option>
          </select>
        </label>
        <Button size="sm" variant="secondary" icon={RefreshCw} disabled={busy}
          onClick={() => { void load(); }}>
          {busy ? 'Loading…' : 'Generate report'}
        </Button>
        <Button size="sm" variant="secondary" icon={Download}
          disabled={!report || busy}
          onClick={download}>Download CSV</Button>
      </div>
    </div>
    {error ? <p role="alert" className="form-error">{error}</p> : null}
    {!report && !error ? <p className="site-report-placeholder" role="status">
      Generate a report to see authenticated daily aggregates. Nothing is exported automatically.
    </p> : null}
    {report ? <>
      <div className="site-report-summary">
        <div><strong>{totals?.pageViews ?? 0}</strong><span>Consented page views</span></div>
        <div><strong>{totals?.ctaClicks ?? 0}</strong><span>Consented CTA clicks</span></div>
        <div><strong>{totals?.acceptedForms ?? 0}</strong><span>Accepted enquiries</span></div>
        <div><strong>{totals?.eventsPublishedToBroker ?? 0}</strong><span>Broker publications</span></div>
        <div><strong>{totals?.eventsRetrying ?? 0}</strong><span>Broker retries</span></div>
        <div><strong>{totals?.missingOutboxEvents ?? 0}</strong><span>Unmatched receipts</span></div>
      </div>
      {hasExceptions ? <p role="alert" className="site-report-warning">
        <AlertTriangle size={18} aria-hidden="true"/> Reconciliation requires investigation.
        Do not recreate leads or infer provider acknowledgement from event-bus publication.
      </p> : null}
      <p className="site-report-window">UTC reporting window: {report.windowStart} through {report.windowEnd}</p>
      <div className="site-report-plot" aria-label="Consented page views by UTC date">
        {report.daily.map((row) => <div className="site-report-plot-row" key={row.date}>
          <span>{row.date}</span>
          <div className="site-report-track"><div className="site-report-bar"
            style={{ width: ((100 * row.pageViews) / highestViews) + '%' }}/></div>
          <strong>{row.pageViews}</strong>
        </div>)}
      </div>
      <div className="site-report-table-wrap">
        <table className="site-report-table">
          <caption>Daily website counts and durable event reconciliation (UTC)</caption>
          <thead><tr>
            <th scope="col">Date</th>
            <th scope="col">Views</th>
            <th scope="col">Clicks</th>
            <th scope="col">Forms</th>
            <th scope="col">Broker</th>
            <th scope="col">Queued</th>
            <th scope="col">Retrying</th>
            <th scope="col">Unmatched</th>
          </tr></thead>
          <tbody>{report.daily.map((row) => <tr key={row.date}>
            <th scope="row">{row.date}</th>
            <td>{row.pageViews}</td><td>{row.ctaClicks}</td><td>{row.acceptedForms}</td>
            <td>{row.eventsPublishedToBroker}</td><td>{row.eventsQueued}</td>
            <td>{row.eventsRetrying}</td><td>{row.missingOutboxEvents}</td>
          </tr>)}</tbody>
        </table>
      </div>
      <p className="site-report-limits">
        <strong>Not a production delivery confirmation.</strong> {report.reconciliationNote}
        {' '}{report.privacyNote}
      </p>
    </> : null}
  </Card>;
}
