import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, GitBranch, Plus, RefreshCw, Save, Trash2 } from 'lucide-react';
import { Badge, Button, Card } from '@/components/ui';
import {
  leadScoringApi,
  type CRMWorkflowJourney,
  type LeadScoreField,
  type LeadScorePreview,
  type LeadScoringPolicy,
} from '@/lib/crm-workflow-api';

const fields: ReadonlyArray<{ value: LeadScoreField; label: string }> = [
  { value: 'source_channel', label: 'Lead source channel' },
  { value: 'utm_source', label: 'UTM source' },
  { value: 'utm_medium', label: 'UTM medium' },
  { value: 'utm_campaign', label: 'UTM campaign' },
];

interface Props {
  journeys: CRMWorkflowJourney[];
  onApplied: () => void;
}

/**
 * Reuses the existing CRM workflow and lead records.
 * No messages, CRM sync, or qualification-state transitions are triggered here.
 */
export function LeadScoringPanel({ journeys, onApplied }: Props) {
  const [saved, setSaved] = useState<LeadScoringPolicy | null>(null);
  const [draft, setDraft] = useState<LeadScoringPolicy | null>(null);
  const [leadId, setLeadId] = useState('');
  const [preview, setPreview] = useState<LeadScorePreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const policy = await leadScoringApi.policy();
      setSaved(policy); setDraft(policy); setPreview(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to load scoring policy.');
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  const dirty = Boolean(saved && draft && JSON.stringify(saved) !== JSON.stringify(draft));
  const modify = (changes: Partial<LeadScoringPolicy>) => {
    setDraft((current) => current ? { ...current, ...changes } : null);
    setPreview(null); setNotice('');
  };

  const save = async () => {
    if (!draft || busy || !dirty) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const policy = await leadScoringApi.savePolicy(draft);
      setSaved(policy); setDraft(policy);
      setPreview(null);
      setNotice('Scoring policy saved as version ' + policy.version + '. No lead was changed.');
    } catch (reason) {
      setError((reason instanceof Error ? reason.message : 'Policy save failed.') +
        ' Your unsaved policy is preserved. Reload before retrying a version conflict.');
    } finally { setBusy(false); }
  };

  const evaluate = async () => {
    if (!leadId || busy || dirty) return;
    setBusy(true); setError(''); setNotice('');
    try {
      setPreview(await leadScoringApi.preview(leadId));
    } catch (reason) {
      setPreview(null);
      setError(reason instanceof Error ? reason.message : 'Unable to preview the selected lead.');
    } finally { setBusy(false); }
  };

  const apply = async () => {
    if (!preview?.eligible || preview.proposed_score === null ||
      preview.current_score === null || preview.current_score === preview.proposed_score || busy || dirty) return;
    if (!window.confirm('Apply this explained score to the selected Lead? Qualification status and messaging will not change.')) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await leadScoringApi.apply(preview.lead_id, preview);
      setPreview(result);
      setNotice('Score saved with an actor-attributed audit event. Qualification status was not changed.');
      onApplied();
    } catch (reason) {
      setPreview(null);
      setError((reason instanceof Error ? reason.message : 'Score was not applied.') +
        ' Reload the current score and policy before retrying.');
    } finally { setBusy(false); }
  };

  return <Card className="crm-lead-scoring">
    <div className="crm-workflow-section-heading">
      <div>
        <h3>Explainable lead scoring</h3>
        <p>Configure bounded rules based on verified attribution fields. Preview before applying a score; qualification and outbound messaging remain separate.</p>
      </div>
      <Button size="sm" variant="secondary" icon={RefreshCw} disabled={busy || loading}
        onClick={() => {
          if (dirty && !window.confirm('Discard unsaved scoring rules?')) return;
          void refresh();
        }}>Reload policy</Button>
    </div>
    {error ? <p className="form-error" role="alert">{error}</p> : null}
    {notice ? <p className="crm-lead-scoring__notice" role="status"><CheckCircle2 size={18} /> {notice}</p> : null}
    {loading ? <p>Loading the workspace scoring policy…</p> : !draft ? <p>Scoring policy could not be loaded.</p> :
      <>
        <p className="crm-lead-scoring__meta">
          <Badge tone={draft.enabled ? 'success' : 'warning'}>{draft.enabled ? 'Enabled' : 'Disabled'}</Badge>
          <span>Policy revision {draft.version} · {draft.rules.length} configured rules</span>
        </p>
        <div className="crm-lead-scoring__settings">
          <label className="crm-lead-scoring__enabled">
            <input type="checkbox" checked={draft.enabled}
              onChange={(e) => modify({ enabled: e.target.checked })}/> Enable scoring previews and application
          </label>
          <label>Starting score (0–100)
            <input type="number" min={0} max={100} value={draft.base_points}
              onChange={(e) => modify({ base_points: Math.min(100, Math.max(0, Number(e.target.value))) })}/>
          </label>
          <label>Human-review threshold (1–100)
            <input type="number" min={1} max={100} value={draft.review_threshold}
              onChange={(e) => modify({ review_threshold: Math.min(100, Math.max(1, Number(e.target.value))) })}/>
          </label>
        </div>
        <div className="crm-lead-scoring__rules">
          <h4>Scoring rules</h4>
          {draft.rules.map((rule, index) => <div className="crm-lead-scoring__rule" key={index}>
            <label>Field
              <select value={rule.field} onChange={(e) =>
                modify({ rules: draft.rules.map((item, i) => i === index
                  ? { ...item, field: e.target.value as LeadScoreField } : item) })}>
                {fields.map((field) => <option key={field.value} value={field.value}>{field.label}</option>)}
              </select>
            </label>
            <label>Equals (case-insensitive)
              <input value={rule.equals} maxLength={120} onChange={(e) =>
                modify({ rules: draft.rules.map((item, i) => i === index
                  ? { ...item, equals: e.target.value } : item) })}/>
            </label>
            <label>Score impact
              <input type="number" min={-50} max={50} value={rule.points} onChange={(e) =>
                modify({ rules: draft.rules.map((item, i) => i === index
                  ? { ...item, points: Math.max(-50, Math.min(50, Number(e.target.value))) } : item) })}/>
            </label>
            <button type="button" aria-label={'Remove scoring rule ' + (index + 1)}
              onClick={() => modify({ rules: draft.rules.filter((_, i) => i !== index) })}>
              <Trash2 size={18}/>
            </button>
          </div>)}
          <div className="crm-lead-scoring__actions">
            <Button variant="secondary" icon={Plus} disabled={busy || draft.rules.length >= 20}
              onClick={() => modify({ rules: [
                ...draft.rules, { field: 'utm_source', equals: '', points: 10 },
              ] })}>Add scoring rule</Button>
            <Button icon={Save} disabled={!dirty || busy || draft.rules.some((r) => !r.equals.trim())}
              onClick={() => { void save(); }}>{busy ? 'Saving…' : 'Save policy'}</Button>
          </div>
          {dirty ? <small role="status">Unsaved policy changes. Save before previewing a lead.</small> : null}
        </div>
        <section className="crm-lead-scoring__preview" aria-label="Lead scoring preview">
          <h4>Preview an existing lead</h4>
          <label>Lead
            <select value={leadId} onChange={(e) => { setLeadId(e.target.value); setPreview(null); }}>
              <option value="">Select a recent lead…</option>
              {journeys.map((journey) => <option key={journey.leadId} value={journey.leadId}>
                {journey.customerName || journey.conversationPublicId || journey.leadId} · {journey.sourceChannel ?? 'direct'}
              </option>)}
            </select>
          </label>
          <Button variant="secondary" icon={GitBranch} disabled={!leadId || busy || dirty}
            onClick={() => { void evaluate(); }}>Preview score</Button>
          {preview ? <div className="crm-lead-scoring__result">
            {preview.eligible ?
              <p><strong>Existing score: {preview.current_score ?? 'Not set'} → Suggested score: {preview.proposed_score}/100</strong>
                {' '}<Badge tone={preview.recommendation === 'review' ? 'warning' : 'neutral'}>
                  {preview.recommendation === 'review' ? 'Human review recommended' : 'Below review threshold'}</Badge>
              </p> :
              <p role="status"><AlertTriangle size={16}/> {preview.ineligible_reason ?? 'Scoring not permitted'}</p>}
            <p>Current qualification: {preview.qualification_status ?? 'Not assigned'} (unchanged by scoring)</p>
            <ul>{preview.rules.map((rule, index) => <li key={index}>
              {rule.field} = {rule.equals}: {rule.matched ? 'Matched' : 'Not matched'} ({rule.points >= 0 ? '+' : ''}{rule.points})
            </li>)}</ul>
            <Button disabled={busy || dirty || !preview.eligible ||
              preview.current_score === preview.proposed_score}
              onClick={() => { void apply(); }}>Apply explained score</Button>
          </div> : null}
        </section>
        <p className="crm-lead-scoring__disclaimer">
          Rule-based scores do not prove a lead is qualified, do not trigger provider delivery,
          and do not override withdrawal of processing consent. CRM routing continues through the existing workflow.
        </p>
      </>}
  </Card>;
}
