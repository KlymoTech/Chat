import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { useLocation, useParams } from 'react-router-dom';
import { CheckCircle2, LockKeyhole, ShieldCheck, SlidersHorizontal } from 'lucide-react';
import { apiConfig } from '@/lib/api';
import './SitePrivacyPage.css';

interface ConsentState {
  policyVersion: string;
  necessary: true;
  analytics: boolean;
  marketing: boolean;
  personalization: boolean;
  globalPrivacyControl: boolean;
  lastUpdated: string | null;
}
type OptionalChoice = Pick<ConsentState, 'analytics' | 'marketing' | 'personalization'>;
const rejected: OptionalChoice = { analytics: false, marketing: false, personalization: false };

const options: Array<{ key: keyof OptionalChoice; label: string; description: string }> = [
  { key: 'analytics', label: 'Analytics', description: 'Understand how public pages are used. Disabled unless you choose it.' },
  { key: 'marketing', label: 'Marketing', description: 'Allow eligible advertising and campaign measurement where configured.' },
  { key: 'personalization', label: 'Personalization', description: 'Allow optional content tailored to permitted visitor preferences.' },
];

function requestUrl(id: string) { return apiConfig.baseUrl + '/site-consent/' + encodeURIComponent(id); }

export function SitePrivacyPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const location = useLocation();
  const [stored, setStored] = useState<ConsentState | null>(null);
  const [choices, setChoices] = useState<OptionalChoice>(rejected);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);

  const refresh = useCallback(async () => {
    if (!workspaceId) return;
    setLoading(true);
    setError('');
    try {
      const response = await fetch(requestUrl(workspaceId), { credentials: 'include', headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error('Unable to load current preferences (' + response.status + ').');
      const state = await response.json() as ConsentState;
      setStored(state);
      setChoices({
        analytics: state.analytics,
        marketing: state.marketing,
        personalization: state.personalization,
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Preferences could not be loaded.');
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => { void refresh(); }, [refresh]);

  const save = async (next: OptionalChoice) => {
    if (!workspaceId || busy) return;
    setBusy(true); setError(''); setSaved(false);
    try {
      const response = await fetch(requestUrl(workspaceId), {
        method: 'POST',
        credentials: 'include',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify(next),
      });
      if (!response.ok) throw new Error('Could not save your choices (' + response.status + ').');
      const state = await response.json() as ConsentState;
      setStored(state);
      setChoices({ analytics: state.analytics, marketing: state.marketing, personalization: state.personalization });
      setSaved(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to save preferences.');
    } finally {
      setBusy(false);
    }
  };

  const backParam = new URLSearchParams(location.search).get('returnTo');
  const expectedPrefix = workspaceId ? '/api/v1/site-cms/public/' + workspaceId + '/' : '';
  const returnTo = backParam && expectedPrefix && backParam.startsWith(expectedPrefix)
    && !backParam.includes('?') && !backParam.includes('#')
    && /^[a-z0-9-]+$/.test(backParam.substring(expectedPrefix.length))
    ? backParam : '/';

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); void save(choices); };

  return <main className="site-privacy-page">
    <div className="site-privacy-panel">
      <div className="site-privacy-mark"><ShieldCheck aria-hidden="true" size={30} /></div>
      <p className="site-privacy-eyebrow">Website privacy preferences</p>
      <h1>You're in control of optional tracking</h1>
      <p>You can use this website without agreeing to optional analytics, advertising, or personalization. Your choices can be changed here at any time.</p>
      {stored?.globalPrivacyControl ? <div className="site-privacy-notice" role="status">
        Your browser signals a Global Privacy Control opt-out. Marketing and personalization remain disabled while that signal is present.
      </div> : null}
      {error ? <div className="site-privacy-error" role="alert">{error}</div> : null}
      {saved ? <div className="site-privacy-success" role="status"><CheckCircle2 size={18} aria-hidden="true"/> Your preferences were saved.</div> : null}
      <form onSubmit={handleSubmit}>
        <fieldset disabled={busy || loading}>
          <legend><SlidersHorizontal size={18} aria-hidden="true"/> Choose your preferences</legend>
          <label className="site-privacy-row">
            <span><strong>Strictly necessary</strong><small>Required for core site security and the basic service.</small></span>
            <span className="site-privacy-always"><LockKeyhole size={15} aria-hidden="true"/> Always active</span>
          </label>
          {options.map((option) => {
            const disabledBySignal = !!stored?.globalPrivacyControl && option.key !== 'analytics';
            return <label className="site-privacy-row" key={option.key}>
              <span><strong>{option.label}</strong><small>{option.description}</small></span>
              <input type="checkbox" checked={disabledBySignal ? false : choices[option.key]}
                disabled={disabledBySignal || busy || loading}
                onChange={(event) => { setSaved(false); setChoices((current) => ({ ...current, [option.key]: event.target.checked })); }}
                aria-label={'Allow ' + option.label.toLowerCase()}/>
            </label>;
          })}
        </fieldset>
        <div className="site-privacy-actions">
          <button type="button" className="site-privacy-secondary" disabled={busy || loading} onClick={() => void save(rejected)}>
            Reject optional tracking
          </button>
          <button type="submit" disabled={busy || loading}>{busy ? 'Saving…' : 'Save my choices'}</button>
          <button type="button" className="site-privacy-secondary" disabled={busy || loading}
            onClick={() => void save({ analytics: true, marketing: true, personalization: true })}>Accept all optional</button>
        </div>
      </form>
      <p className="site-privacy-note">A consent record is saved using an anonymous browser cookie. No optional preference is enabled by default. This preference screen does not replace the website's full privacy notice or legal rights process.</p>
      <a href={returnTo} className="site-privacy-back">Return to website</a>
      {stored?.lastUpdated ? <p className="site-privacy-date">Last updated: {new Date(stored.lastUpdated).toLocaleString()}</p> : null}
    </div>
  </main>;
}
