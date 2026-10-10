import { useState } from 'react';
import { AlertTriangle, CheckCircle2, RefreshCw, ShieldAlert } from 'lucide-react';
import { Button, Card } from '@/components/ui';
import { request } from '@/lib/api';
import './WebsiteContentPreflight.css';

interface ContentIssue {
  code: string;
  severity: 'blocker' | 'warning';
  resourceType: 'page' | 'form' | 'menu' | 'redirect' | 'site';
  slug: string;
  message: string;
}

interface ContentPreflight {
  scope: 'cms-content-only';
  contentReady: boolean;
  releaseCertified: false;
  checkedAt: string;
  summary: {
    publishedPages: number;
    publishedForms: number;
    enabledRedirects: number;
    blockers: number;
    warnings: number;
  };
  issues: ContentIssue[];
  verificationLimits: string;
}

/** Owner-facing integrity check; intentionally not labelled deployment certification. */
export function WebsiteContentPreflight() {
  const [report, setReport] = useState<ContentPreflight | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const run = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    setReport(null);
    try {
      const next = await request<ContentPreflight>('/site-cms/preflight');
      if (next.scope !== 'cms-content-only' || next.releaseCertified !== false) {
        throw new Error('Unexpected website preflight report type');
      }
      setReport(next);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to inspect website publication.');
    } finally {
      setBusy(false);
    }
  };

  return <Card>
    <div className="site-preflight-heading">
      <div>
        <h3>Website content preflight</h3>
        <p>Check live CMS pages, published forms, navigation, and redirects before sharing public URLs.</p>
      </div>
      <Button variant="secondary" icon={RefreshCw} size="sm"
        disabled={busy} onClick={() => { void run(); }}>
        {busy ? 'Checking…' : 'Run content checks'}
      </Button>
    </div>
    {error ? <p className="form-error" role="alert">
      <ShieldAlert size={16} /> {error}. No readiness claim can be made until this check succeeds.
    </p> : null}
    {!report && !error ? <p className="site-preflight-placeholder">
      No content verification has been run in this view. Run the check after publishing or archiving.
    </p> : null}
    {report ? <>
      <div role="status" className="site-preflight-status">
        {report.contentReady ? <CheckCircle2 size={22} color="#047857" />
          : <AlertTriangle size={22} color="#b45309" />}
        <div>
          <strong>{report.contentReady
            ? 'Stored content checks passed'
            : report.summary.blockers + ' content blockers need attention'}</strong>
          <p>{report.summary.publishedPages} published pages · {report.summary.publishedForms} published forms ·
            {' '}{report.summary.enabledRedirects} active redirects · {report.summary.warnings} warnings</p>
        </div>
      </div>
      {report.issues.length ? <div className="site-preflight-results">
        <table>
          <caption>Published website integrity findings</caption>
          <thead>
            <tr><th scope="col">Level</th><th scope="col">Resource</th><th scope="col">Action needed</th></tr>
          </thead>
          <tbody>{report.issues.map((issue, index) => <tr key={issue.code + ':' + issue.slug + ':' + index}>
            <td>{issue.severity === 'blocker' ? 'Blocker' : 'Warning'}</td>
            <td>{issue.resourceType}{issue.slug ? ': /' + issue.slug : ''}</td>
            <td>{issue.message}</td>
          </tr>)}</tbody>
        </table>
      </div> : <p>No broken internal publication references were found.</p>}
      <p className="site-preflight-limits">
        <strong>Production release is not certified.</strong> {report.verificationLimits}
      </p>
      <small>Content check last run: {new Date(report.checkedAt).toLocaleString()}</small>
    </> : null}
  </Card>;
}
