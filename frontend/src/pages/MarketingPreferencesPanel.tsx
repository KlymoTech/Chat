import { useEffect, useState } from 'react';
import { CheckCircle2, Copy, RefreshCw, ShieldCheck, ShieldOff } from 'lucide-react';
import { Badge, Button, Card } from '@/components/ui';
import { marketingPreferencesApi, type CRMWorkflowJourney, type LeadMarketingPreferences } from '@/lib/crm-workflow-api';
import './MarketingPreferencesPanel.css';

/** Uses the existing CRM, Lead and consent ledger. No marketing sends here. */
export function MarketingPreferencesPanel({ journeys }: { journeys: CRMWorkflowJourney[] }) {
  const [leadId, setLeadId] = useState('');
  const [preferences, setPreferences] = useState<LeadMarketingPreferences | null>(null);
  const [signedLink, setSignedLink] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [note, setNote] = useState('');

  useEffect(() => {
    setPreferences(null); setSignedLink(''); setNote(''); setError('');
  }, [leadId]);

  const refresh = async () => {
    if (!leadId || busy) return;
    setBusy(true); setError(''); setSignedLink(''); setNote('');
    try { setPreferences(await marketingPreferencesApi.get(leadId)); }
    catch (reason) {
      setPreferences(null);
      setError(reason instanceof Error ? reason.message : 'Cannot read marketing permission');
    } finally { setBusy(false); }
  };

  const withdraw = async () => {
    if (!leadId || busy || !window.confirm(
      'Withdraw marketing permission? This will not revoke enquiry-processing consent or erase the lead.',
    )) return;
    setBusy(true); setError(''); setNote(''); setSignedLink('');
    try {
      const result = await marketingPreferencesApi.withdraw(leadId);
      setPreferences(await marketingPreferencesApi.get(leadId));
      setNote(result.changed ? 'Marketing permission withdrawn and audited.'
        : 'Marketing permission was already suppressed; no duplicate record was created.');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not withdraw permission');
    } finally { setBusy(false); }
  };

  const createLink = async () => {
    if (!leadId || busy) return;
    setBusy(true); setError(''); setNote(''); setSignedLink('');
    try {
      const result = await marketingPreferencesApi.createUnsubscribeLink(leadId);
      setSignedLink(marketingPreferencesApi.publicUrl(result.path));
      setNote('Link expires in ' + result.expiresIn + '. Share only with this lead.');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not create unsubscribe link');
    } finally { setBusy(false); }
  };

  const copyLink = async () => {
    if (!signedLink) return;
    try {
      await navigator.clipboard.writeText(signedLink);
      setNote('Confidential unsubscribe link copied.');
    } catch {
      setError('Clipboard access unavailable. Select and copy the displayed link manually.');
    }
  };

  return <Card className="crm-marketing-permission">
    <div>
      <h3>Marketing consent and suppression</h3>
      <p>Review purpose-specific marketing permission, suppress contact and create a signed unsubscribe link.
        Enquiry processing remains independent.</p>
    </div>
    <div className="crm-marketing-permission__controls">
      <label>Lead
        <select value={leadId} onChange={(event) => setLeadId(event.target.value)}>
          <option value="">Select a lead…</option>
          {journeys.map((journey) => <option value={journey.leadId} key={journey.leadId}>
            {journey.customerName || journey.conversationPublicId || journey.leadId}
          </option>)}
        </select>
      </label>
      <Button variant="secondary" size="sm" icon={RefreshCw} disabled={!leadId || busy}
        onClick={() => { void refresh(); }}>Check permission</Button>
    </div>
    {error && <p className="form-error" role="alert">{error}</p>}
    {note && <p role="status" className="crm-marketing-permission__success">
      <CheckCircle2 size={17} aria-hidden="true" /> {note}
    </p>}
    {preferences && <div className="crm-marketing-permission__result">
      <div className="crm-marketing-permission__status">
        <span>Marketing: </span>
        <Badge tone={preferences.marketingAllowed ? 'success' : 'warning'}>
          {preferences.marketingStatus}
        </Badge>
      </div>
      <p><ShieldCheck size={17} aria-hidden="true" /> Enquiry-processing permission is not modified.</p>
      {preferences.marketingStatus === 'pending_verification' && <p role="status">
        An earlier marketing withdrawal was found for this contact address.
        Reconfirmation is required before marketing can be permitted.
      </p>}
      <p>{preferences.note}</p>
      <div className="crm-marketing-permission__actions">
        <Button variant="secondary" icon={ShieldOff}
          disabled={busy || ['withdrawn', 'revoked', 'denied', 'opted_out', 'suppressed'].includes(preferences.marketingStatus)}
          onClick={() => { void withdraw(); }}>Withdraw marketing permission</Button>
        <Button variant="secondary" icon={Copy} disabled={busy}
          onClick={() => { void createLink(); }}>Create unsubscribe link</Button>
      </div>
      {signedLink && <div className="crm-marketing-permission__link">
        <label>Signed, 30-day link (intended recipient only)
          <input readOnly value={signedLink} onFocus={(event) => event.target.select()} />
        </label>
        <Button variant="secondary" icon={Copy} disabled={busy}
          onClick={() => { void copyLink(); }}>Copy link</Button>
      </div>}
    </div>}
    <p className="crm-marketing-permission__disclaimer">
      Unknown permission is not a grant. No marketing messages are sent by this panel.
      Future outbound providers must recheck the latest consent before each send.
    </p>
  </Card>;
}
