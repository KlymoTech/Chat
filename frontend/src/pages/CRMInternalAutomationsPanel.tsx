import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Plus, RefreshCw, Save, Search, ShieldCheck, Trash2 } from 'lucide-react';
import { Badge, Button, Card } from '@/components/ui';
import {
  internalAutomationsApi,
  leadSegmentsApi,
  type InternalLeadAutomation,
  type InternalLeadAutomationPreview,
  type InternalLeadAutomationRegister,
  type InternalLeadAutomationRun,
  type LeadSegment,
} from '@/lib/crm-workflow-api';
import './CRMInternalAutomationsPanel.css';

/**
 * Uses the already-deployed /crm/workflow/internal-automations endpoints,
 * existing segments and in-app notification system. No new CRM/lead engine.
 * Save does not execute; preview does not execute; execute is human-confirmed.
 */
export function CRMInternalAutomationsPanel() {
  const [stored, setStored] = useState<InternalLeadAutomationRegister | null>(null);
  const [draft, setDraft] = useState<InternalLeadAutomationRegister | null>(null);
  const [segments, setSegments] = useState<LeadSegment[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [preview, setPreview] = useState<InternalLeadAutomationPreview | null>(null);
  const [lastRun, setLastRun] = useState<InternalLeadAutomationRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true); setError(''); setNotice(''); setPreview(null); setLastRun(null);
    try {
      const [register, segmentRegister] = await Promise.all([
        internalAutomationsApi.list(),
        leadSegmentsApi.list(),
      ]);
      setStored(register);
      setDraft(register);
      setSegments(segmentRegister.segments);
      setSelectedId((previous) => register.automations.some((item) => item.id === previous)
        ? previous : register.automations[0]?.id ?? '');
    } catch (reason) {
      setStored(null);
      setDraft(null);
      setSegments([]);
      setError(reason instanceof Error ? reason.message : 'Could not load review automations.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const operationsSegments = useMemo(
    () => segments.filter((segment) => segment.enabled && segment.purpose === 'operations'),
    [segments],
  );
  const selected = draft?.automations.find((item) => item.id === selectedId) ?? null;
  const dirty = Boolean(stored && draft && JSON.stringify(stored) !== JSON.stringify(draft));
  const eligibleSegment = Boolean(selected
    && operationsSegments.some((item) => item.id === selected.segment_id));
  const valid = Boolean(draft && draft.automations.length <= 12
    && new Set(draft.automations.map((item) => item.id)).size === draft.automations.length
    && draft.automations.every((item) => item.name.trim().length >= 3
      && item.name.trim().length <= 100
      && item.max_per_run >= 1 && item.max_per_run <= 50
      && (!item.enabled || operationsSegments.some((segment) => segment.id === item.segment_id))));

  const modify = (updated: InternalLeadAutomation) => {
    setDraft((current) => current ? {
      ...current,
      automations: current.automations.map((item) => item.id === updated.id ? updated : item),
    } : null);
    setPreview(null); setLastRun(null); setError(''); setNotice('');
  };

  const addAutomation = () => {
    if (!draft || draft.automations.length >= 12) return;
    const created: InternalLeadAutomation = {
      id: crypto.randomUUID(),
      name: 'New internal lead review',
      segment_id: operationsSegments[0]?.id ?? '',
      enabled: false,
      action: 'notify_admins',
      max_per_run: 25,
    };
    setDraft({ ...draft, automations: [...draft.automations, created] });
    setSelectedId(created.id);
    setPreview(null); setLastRun(null); setNotice(''); setError('');
  };

  const removeAutomation = () => {
    if (!selected || !draft) return;
    if (!window.confirm('Remove this automation definition from the draft? Previously queued reviews remain in the audit history.')) return;
    const next = draft.automations.filter((item) => item.id !== selected.id);
    setDraft({ ...draft, automations: next });
    setSelectedId(next[0]?.id ?? '');
    setPreview(null); setLastRun(null); setNotice(''); setError('');
  };

  const save = async () => {
    if (!draft || busy || !valid || !dirty) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await internalAutomationsApi.save(draft);
      setStored(result);
      setDraft(result);
      setPreview(null);
      setLastRun(null);
      setNotice('Review automation definitions saved as version ' + result.version
        + '. No leads were contacted and no reviews were queued.');
    } catch (reason) {
      setError((reason instanceof Error ? reason.message : 'Could not save automations.')
        + ' Your unsaved draft remains visible; reload after resolving any version conflict.');
    } finally {
      setBusy(false);
    }
  };

  const simulate = async () => {
    if (!selected || busy || dirty || !selected.enabled || !eligibleSegment) return;
    setBusy(true); setError(''); setNotice(''); setPreview(null); setLastRun(null);
    try {
      const result = await internalAutomationsApi.preview(selected.id);
      if (result.automationId !== selected.id || result.externalDelivery !== false
        || !/^[0-9a-f]{64}$/.test(result.eligibleFingerprint)) {
        throw new Error('The server returned an unexpected automation preview.');
      }
      setPreview(result);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Automation simulation failed.');
    } finally {
      setBusy(false);
    }
  };

  const execute = async () => {
    if (!selected || !preview || busy || dirty
      || preview.automationId !== selected.id
      || preview.truncated || preview.remainingEligible <= 0
      || preview.externalDelivery !== false
      || !/^[0-9a-f]{64}$/.test(preview.eligibleFingerprint)) return;
    if (!window.confirm(
      'Queue up to ' + selected.max_per_run
      + ' in-app lead-review notifications for workspace administrators?'
      + ' No customer messages or CRM writes will be sent.',
    )) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await internalAutomationsApi.execute(selected.id, preview);
      if (result.externalDelivery !== false) {
        throw new Error('The server did not confirm internal-only execution.');
      }
      setLastRun(result);
      setPreview(null);
      setNotice(result.queuedReviews + ' internal lead reviews queued. '
        + result.previouslyQueued + ' previously handled leads were skipped. '
        + 'No customers were contacted.');
    } catch (reason) {
      setPreview(null); setLastRun(null);
      setError((reason instanceof Error ? reason.message : 'Automation execution failed.')
        + ' Simulate again before any retry; the recipient count or rules may have changed.');
    } finally {
      setBusy(false);
    }
  };

  return <Card className="crm-internal-automations">
    <div className="crm-workflow-section-heading">
      <div>
        <h3>Internal lead-review automations</h3>
        <p>Reuse approved operational segments to queue deduplicated, in-app reviews for administrators.
          Simulation is read-only. Customer-facing marketing and external CRM actions are not supported by this workflow.</p>
      </div>
      <Button variant="secondary" size="sm" icon={RefreshCw} disabled={busy || loading}
        onClick={() => {
          if (!dirty || window.confirm('Discard unsaved review automation changes?')) void refresh();
        }}>Reload automations</Button>
    </div>
    {error ? <p className="form-error" role="alert"><AlertTriangle size={16}/> {error}</p> : null}
    {notice ? <p role="status" className="crm-internal-automations__notice">
      <CheckCircle2 size={16}/> {notice}
    </p> : null}
    {loading ? <p>Loading review automations…</p> : !draft
      ? <p>Review automations are unavailable until the workspace API responds.</p>
      : <>
        {operationsSegments.length === 0 ? <p role="status" className="crm-internal-automations__warning">
          Save and enable an <strong>operations</strong> segment above before activating automated reviews.
          Marketing-purpose segments cannot be used for operational notifications.
        </p> : null}
        <div className="crm-internal-automations__picker">
          <label>Automation
            <select value={selectedId} onChange={(event) => {
              setSelectedId(event.target.value);
              setPreview(null); setLastRun(null); setError(''); setNotice('');
            }}>
              {!selected && <option value="">Select an automation…</option>}
              {draft.automations.map((item) => <option key={item.id} value={item.id}>
                {item.name} {item.enabled ? '(enabled)' : '(disabled)'}
              </option>)}
            </select>
          </label>
          <Button variant="secondary" size="sm" icon={Plus}
            disabled={busy || draft.automations.length >= 12}
            onClick={addAutomation}>Add automation</Button>
        </div>
        {selected ? <div className="crm-internal-automations__editor">
          <div className="crm-internal-automations__fields">
            <label>Automation name
              <input maxLength={100} value={selected.name}
                onChange={(event) => modify({ ...selected, name: event.target.value })}/>
            </label>
            <label>Enabled operational segment
              <select value={selected.segment_id}
                onChange={(event) => modify({ ...selected, segment_id: event.target.value })}>
                {!eligibleSegment && <option value={selected.segment_id}>
                  {selected.segment_id ? 'Unavailable or disabled segment' : 'Choose an operations segment…'}
                </option>}
                {operationsSegments.map((segment) => <option key={segment.id} value={segment.id}>
                  {segment.name}
                </option>)}
              </select>
            </label>
            <label>Maximum reviews per execution (1–50)
              <input type="number" min={1} max={50} value={selected.max_per_run}
                onChange={(event) => modify({
                  ...selected, max_per_run: Math.min(50, Math.max(1, Number(event.target.value))),
                })}/>
            </label>
            <label className="crm-internal-automations__toggle">
              <input type="checkbox" checked={selected.enabled}
                disabled={!eligibleSegment && !selected.enabled}
                onChange={(event) => modify({ ...selected, enabled: event.target.checked })}/>
              Enable internal administrator review
            </label>
          </div>
          <div className="crm-internal-automations__actions">
            <Button variant="secondary" size="sm" icon={Trash2} disabled={busy}
              onClick={removeAutomation}>Remove draft definition</Button>
            <Button icon={Save} disabled={busy || !dirty || !valid}
              onClick={() => { void save(); }}>Save automation rules</Button>
            <Button variant="secondary" icon={Search}
              disabled={busy || dirty || !selected.enabled || !eligibleSegment}
              onClick={() => { void simulate(); }}>Simulate without changes</Button>
          </div>
          {dirty ? <p role="status">Save your changes before simulating or queuing review notifications.</p> : null}
          {!valid ? <p className="form-error" role="alert">
            Active automations require valid names and an enabled operational segment.
          </p> : null}
          {preview && <div className="crm-internal-automations__preview" aria-label="Automation simulation">
            <h4>Read-only simulation</h4>
            <p>Eligible leads: <strong>{preview.eligibleLeads}</strong> ·
              {' '}Already queued: <strong>{preview.alreadyQueued}</strong> ·
              {' '}Remaining: <strong>{preview.remainingEligible}</strong></p>
            <p>Consent/status blocked: {preview.blockedByConsentOrStatus} ·
              {' '}Missing rule data: {preview.unknownInputLeads} ·
              {' '}Examined: {preview.examinedLeads}</p>
            <Badge tone={preview.truncated ? 'danger' : 'neutral'}>
              {preview.truncated ? 'Safety limit exceeded' : 'Bounded preview'}
            </Badge>
            <p>{preview.note}</p>
            <Button icon={ShieldCheck}
              disabled={busy || preview.truncated || preview.remainingEligible <= 0
                || preview.externalDelivery !== false}
              onClick={() => { void execute(); }}>Confirm and queue internal reviews</Button>
          </div>}
          {lastRun && <div className="crm-internal-automations__result" role="status">
            <strong>Execution result</strong>
            <p>Queued: {lastRun.queuedReviews} · Previously queued: {lastRun.previouslyQueued} ·
              {' '}No recipients: {lastRun.noRecipients} · Still eligible: {lastRun.remainingEligible}</p>
            <p>{lastRun.note}</p>
          </div>}
        </div> : <p>No automations yet. Add one to create an internal review rule.</p>}
        <p className="crm-internal-automations__disclaimer">
          No customer emails, WhatsApp messages, lead qualification updates, or external CRM provider writes
          occur through this panel. The backend revalidates consent, segments, versions, and bounded scan limits at execution time.
        </p>
      </>}
  </Card>;
}
