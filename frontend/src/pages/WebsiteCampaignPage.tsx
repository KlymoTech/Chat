import { useState, type FormEvent } from 'react';
import { CheckCircle2, Copy, ExternalLink, Link2, RotateCcw, ShieldCheck } from 'lucide-react';
import { Button, Card } from '@/components/ui';
import { request } from '@/lib/api';
import { useWorkspace } from '@/components/providers';
import './WebsiteCampaignPage.css';

type CampaignInput = {
  destination: string;
  source: string;
  medium: string;
  campaign: string;
  content: string;
  term: string;
};
type CampaignResult = { url: string; source: string; medium: string; campaign: string };

const defaults: CampaignInput = {
  destination: '',
  source: 'newsletter',
  medium: 'email',
  campaign: '',
  content: '',
  term: '',
};

function failureText(cause: unknown): string {
  if (cause instanceof Error) {
    const parsed = cause as Error & { detail?: unknown };
    const detail = parsed.detail;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail === 'object' && 'detail' in detail) {
      const nested = (detail as { detail: unknown }).detail;
      if (typeof nested === 'string') return nested;
    }
    return cause.message;
  }
  return 'Unable to generate the campaign URL.';
}

export function WebsiteCampaignPage() {
  const { activeWorkspace } = useWorkspace();
  const [form, setForm] = useState<CampaignInput>(defaults);
  const [generated, setGenerated] = useState<CampaignResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState('');

  const change = (key: keyof CampaignInput, value: string) => {
    setForm((old) => ({ ...old, [key]: value }));
    setGenerated(null);
    setCopied(false);
    setError('');
  };

  const build = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!activeWorkspace || busy) return;
    setError('');
    setCopied(false);
    setBusy(true);
    try {
      const result = await request<CampaignResult>('/site-campaigns/url', {
        method: 'POST',
        body: JSON.stringify({
          destination: form.destination.trim(),
          source: form.source.trim(),
          medium: form.medium.trim(),
          campaign: form.campaign.trim(),
          ...(form.content.trim() ? { content: form.content.trim() } : {}),
          ...(form.term.trim() ? { term: form.term.trim() } : {}),
        }),
      });
      setGenerated(result);
    } catch (cause) {
      setError(failureText(cause));
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!generated) return;
    try {
      await navigator.clipboard.writeText(generated.url);
      setCopied(true);
      setError('');
    } catch {
      setCopied(false);
      setError('Clipboard access is unavailable. You can select the generated URL and copy it manually.');
    }
  };

  return <div className="page website-campaigns">
    <div className="page-heading page-heading--split">
      <div>
        <h2>Website campaign links</h2>
        <p>Build consistent UTM-tagged campaign URLs for approved landing pages.</p>
      </div>
      <Button variant="secondary" icon={RotateCcw} disabled={busy}
        onClick={() => { setForm(defaults); setGenerated(null); setCopied(false); setError(''); }}>
        Reset form
      </Button>
    </div>

    {!activeWorkspace ? <Card><p>Select a workspace to manage its website campaigns.</p></Card> :
      <div className="website-campaigns-grid">
        <Card>
          <h3>Generate a tracked link</h3>
          <form className="website-campaigns-form" onSubmit={(event) => { void build(event); }}>
            <label>Landing page (HTTPS URL)
              <input type="url" required placeholder="https://yourdomain.example/landing"
                value={form.destination} maxLength={2048}
                onChange={(event) => change('destination', event.target.value)} />
            </label>
            <div className="website-campaigns-double">
              <label>Campaign source
                <input required maxLength={120} placeholder="newsletter"
                  value={form.source} onChange={(event) => change('source', event.target.value)} />
              </label>
              <label>Campaign medium
                <select value={form.medium} onChange={(event) => change('medium', event.target.value)}>
                  <option value="email">Email</option>
                  <option value="cpc">Paid search (CPC)</option>
                  <option value="social">Organic social</option>
                  <option value="paid_social">Paid social</option>
                  <option value="referral">Referral</option>
                  <option value="qr">QR code</option>
                  <option value="organic">Organic</option>
                </select>
              </label>
            </div>
            <label>Campaign name
              <input required maxLength={120} placeholder="october_launch"
                value={form.campaign} onChange={(event) => change('campaign', event.target.value)} />
            </label>
            <div className="website-campaigns-double">
              <label>Content variation (optional)
                <input maxLength={120} placeholder="hero_cta"
                  value={form.content} onChange={(event) => change('content', event.target.value)} />
              </label>
              <label>Keyword (optional)
                <input maxLength={120} placeholder="product_name"
                  value={form.term} onChange={(event) => change('term', event.target.value)} />
              </label>
            </div>
            <p className="website-campaigns-help">
              Existing non-UTM query parameters are preserved. Existing UTM parameters are replaced.
              The backend validates URLs and refuses unsupported schemes.
            </p>
            <Button type="submit" icon={Link2} disabled={busy || !form.destination.trim() || !form.campaign.trim()}>
              {busy ? 'Generating…' : 'Generate URL'}
            </Button>
          </form>
        </Card>
        <div className="website-campaigns-results">
          <Card>
            <h3>Generated campaign URL</h3>
            {error ? <p className="website-campaigns-error" role="alert">{error}</p> : null}
            {generated ? <>
              <label className="website-campaigns-output-label" htmlFor="campaign-output">Validated destination</label>
              <textarea id="campaign-output" readOnly rows={6} value={generated.url}
                onFocus={(event) => event.target.select()} />
              <div className="website-campaigns-actions">
                <Button icon={Copy} onClick={() => { void copy(); }}>{copied ? 'Copied!' : 'Copy URL'}</Button>
                <a className="website-campaigns-visit" href={generated.url}
                  target="_blank" rel="noopener noreferrer">
                  Preview destination <ExternalLink size={16} aria-hidden="true" />
                </a>
              </div>
              {copied ? <p role="status" className="website-campaigns-success">
                <CheckCircle2 size={17} aria-hidden="true" /> Link copied.
              </p> : null}
            </> : <p>Complete the form to generate a validated link. No campaign traffic is sent while you create the URL.</p>}
          </Card>
          <Card>
            <div className="website-campaigns-advice-heading">
              <ShieldCheck aria-hidden="true" size={23} />
              <h3>Measurement and privacy</h3>
            </div>
            <p>UTM tags identify campaign sources, not individual visitors. Use your website's consent-aware analytics and actual business outcomes to evaluate performance.</p>
            <p>Ad delivery, CRM updates and conversion reporting require their separate configured integrations. Generating a link does not activate or verify those services.</p>
          </Card>
        </div>
      </div>}
  </div>;
}
