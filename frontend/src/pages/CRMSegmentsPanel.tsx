import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Plus, RefreshCw, Save, Search, Trash2 } from 'lucide-react';
import { Button, Card } from '@/components/ui';
import {
  leadSegmentsApi,
  type LeadSegment, type LeadSegmentCondition, type LeadSegmentField,
  type LeadSegmentPreview, type LeadSegmentRegister,
} from '@/lib/crm-workflow-api';
import './CRMSegmentsPanel.css';

const fields: Array<{ value: LeadSegmentField; label: string }> = [
  { value: 'source_channel', label: 'Lead source' },
  { value: 'utm_source', label: 'UTM source' },
  { value: 'utm_medium', label: 'UTM medium' },
  { value: 'utm_campaign', label: 'UTM campaign' },
  { value: 'lifecycle_status', label: 'Lead lifecycle status' },
  { value: 'qualification_status', label: 'Human qualification status' },
];

const standardCondition = (): LeadSegmentCondition => ({
  field: 'source_channel', equals: 'website_form',
});

export function CRMSegmentsPanel() {
  const [stored, setStored] = useState<LeadSegmentRegister | null>(null);
  const [draft, setDraft] = useState<LeadSegmentRegister | null>(null);
  const [selectedId, setSelectedId] = useState('');
  const [preview, setPreview] = useState<LeadSegmentPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true); setError(''); setNotice('');
    try {
      const fresh = await leadSegmentsApi.list();
      setStored(fresh); setDraft(fresh);
      setSelectedId((id) => fresh.segments.some((item) => item.id === id)
        ? id : fresh.segments[0]?.id ?? '');
      setPreview(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not load segments.');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const selected = draft?.segments.find((segment) => segment.id === selectedId);
  const dirty = Boolean(stored && draft && JSON.stringify(stored) !== JSON.stringify(draft));
  const modifySegment = (updated: LeadSegment) => {
    setDraft((previous) => previous ? {
      ...previous,
      segments: previous.segments.map((item) => item.id === updated.id ? updated : item),
    } : null);
    setPreview(null); setError(''); setNotice('');
  };
  const create = () => {
    if (!draft || draft.segments.length >= 15) return;
    const item: LeadSegment = {
      id: crypto.randomUUID(), name: 'New segment',
      purpose: 'operations', enabled: false,
      logic: 'all', include: [standardCondition()], exclude: [],
    };
    setDraft({ ...draft, segments: [...draft.segments, item] });
    setSelectedId(item.id); setPreview(null); setNotice('');
  };
  const editRules = (
    segment: LeadSegment,
    kind: 'include' | 'exclude',
    rules: LeadSegmentCondition[],
  ) => modifySegment({ ...segment, [kind]: rules });

  const valid = Boolean(draft && draft.segments.length <= 15 &&
    new Set(draft.segments.map((segment) => segment.id)).size === draft.segments.length &&
    draft.segments.every((segment) => segment.name.trim().length >= 3
      && segment.include.length >= 1 && segment.include.length <= 6
      && segment.exclude.length <= 6
      && [...segment.include, ...segment.exclude].every(
        (rule) => rule.equals.trim().length > 0 && rule.equals.trim().length <= 160,
      )));

  const save = async () => {
    if (!draft || !dirty || !valid || busy) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const saved = await leadSegmentsApi.save(draft);
      setStored(saved); setDraft(saved); setPreview(null);
      setNotice('Segment definitions saved as workspace version ' + saved.version +
        '. No messages were sent or customer records changed.');
    } catch (reason) {
      setError((reason instanceof Error ? reason.message : 'Segment save failed.') +
        ' Unsaved rules are still visible; reload before resolving a version conflict.');
    } finally { setBusy(false); }
  };

  const inspect = async () => {
    if (!selected || busy || dirty) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const summary = await leadSegmentsApi.preview(selected.id);
      setPreview(summary);
    } catch (reason) {
      setPreview(null);
      setError(reason instanceof Error ? reason.message : 'Segment preview unavailable.');
    } finally { setBusy(false); }
  };

  return <Card className="crm-segments">
    <div className="crm-workflow-section-heading">
      <div>
        <h3>Consent-aware Lead segments</h3>
        <p>Preview bounded, explainable audiences from existing CRM fields. Marketing segments require separate explicit marketing consent and never send messages automatically.</p>
      </div>
      <Button variant="secondary" size="sm" icon={RefreshCw} disabled={busy || loading}
        onClick={() => {
          if (!dirty || window.confirm('Discard unsaved segment edits?')) void refresh();
        }}>Reload segments</Button>
    </div>
    {error ? <p role="alert" className="form-error">{error}</p> : null}
    {notice ? <p role="status" className="crm-segments__notice">{notice}</p> : null}
    {loading ? <p>Loading segment definitions…</p> : !draft ? <p>Segments are currently unavailable.</p> : <>
      <div className="crm-segments__picker">
        <label>Segment
          <select value={selectedId} onChange={(event) => { setSelectedId(event.target.value); setPreview(null); }}>
            {!selectedId && <option value="">Select a segment…</option>}
            {draft.segments.map((segment) => <option key={segment.id} value={segment.id}>
              {segment.name} · {segment.purpose}
            </option>)}
          </select>
        </label>
        <Button variant="secondary" size="sm" icon={Plus}
          disabled={busy || draft.segments.length >= 15} onClick={create}>Create segment</Button>
      </div>
      {selected ? <div className="crm-segments__editor">
        <div className="crm-segments__metadata">
          <label>Segment name
            <input value={selected.name} maxLength={100}
              onChange={(event) => modifySegment({ ...selected, name: event.target.value })}/>
          </label>
          <label>Authorized purpose
            <select value={selected.purpose} onChange={(event) =>
              modifySegment({ ...selected,
                purpose: event.target.value as LeadSegment['purpose'] })}>
              <option value="operations">Internal operational review</option>
              <option value="marketing">Marketing (explicit consent required)</option>
            </select>
          </label>
          <label>Include logic
            <select value={selected.logic} onChange={(event) =>
              modifySegment({ ...selected, logic: event.target.value as LeadSegment['logic'] })}>
              <option value="all">Match all inclusion rules (AND)</option>
              <option value="any">Match at least one inclusion rule (OR)</option>
            </select>
          </label>
          <label className="crm-segments__toggle">
            <input type="checkbox" checked={selected.enabled}
              onChange={(event) => modifySegment({ ...selected, enabled: event.target.checked })}/>
            Enable this segment definition
          </label>
        </div>
        {(['include', 'exclude'] as const).map((kind) => <fieldset key={kind} className="crm-segments__rules">
          <legend>{kind === 'include' ? 'Include matching Leads' : 'Exclude matching Leads'}</legend>
          <p>{kind === 'exclude' ? 'Any matching exclusion rule removes a lead.' :
            'Missing attribution is unknown, not evidence that a lead lacks interest.'}</p>
          {selected[kind].map((rule, index) => <div className="crm-segments__rule" key={index}>
            <label>Field
              <select value={rule.field} onChange={(event) => editRules(selected, kind,
                selected[kind].map((item, i) => i === index
                  ? { ...item, field: event.target.value as LeadSegmentField } : item))}>
                {fields.map((field) => <option key={field.value} value={field.value}>{field.label}</option>)}
              </select>
            </label>
            <label>Equals (case-insensitive)
              <input maxLength={160} value={rule.equals}
                onChange={(event) => editRules(selected, kind,
                  selected[kind].map((item, i) => i === index
                    ? { ...item, equals: event.target.value } : item))}/>
            </label>
            <button type="button" aria-label={'Remove ' + kind + ' rule ' + (index + 1)}
              disabled={kind === 'include' && selected.include.length === 1}
              onClick={() => editRules(selected, kind,
                selected[kind].filter((_, i) => i !== index))}>
              <Trash2 size={18}/>
            </button>
          </div>)}
          <Button variant="secondary" icon={Plus} size="sm"
            disabled={busy || selected[kind].length >= 6}
            onClick={() => editRules(selected, kind, [...selected[kind], standardCondition()])}>
            Add {kind} condition
          </Button>
        </fieldset>)}
        <div className="crm-segments__actions">
          <Button variant="secondary" icon={Trash2} disabled={busy}
            onClick={() => {
              if (!window.confirm('Delete this draft segment definition? No existing Lead will be deleted.')) return;
              const remaining = draft.segments.filter((item) => item.id !== selected.id);
              setDraft({ ...draft, segments: remaining });
              setSelectedId(remaining[0]?.id ?? ''); setPreview(null);
            }}>Remove segment</Button>
          <Button icon={Save} disabled={busy || !dirty || !valid}
            onClick={() => { void save(); }}>{busy ? 'Saving…' : 'Save definitions'}</Button>
          <Button variant="secondary" icon={Search} disabled={busy || dirty}
            onClick={() => { void inspect(); }}>Preview eligible count</Button>
        </div>
        {dirty ? <p role="status">Unsaved policy changes. Save before previewing.</p> : null}
        {preview ? <section className="crm-segments__preview" aria-label="Segment population preview">
          <h4>Source-system preview</h4>
          <div className="crm-segments__counts">
            <div><strong>{preview.matchedLeads}</strong><span>Rule matches and eligible</span></div>
            <div><strong>{preview.blockedByEligibility}</strong><span>Consent/status excluded</span></div>
            <div><strong>{preview.unknownInputLeads}</strong><span>Unknown rule inputs</span></div>
            <div><strong>{preview.examinedLeads}</strong><span>Leads examined</span></div>
          </div>
          {preview.truncated ? <p role="alert"><AlertTriangle size={17} />
            Preview limit reached. Numbers are incomplete, not full audience totals.</p> : null}
          <p>{preview.note}</p>
          <small>Policy v{preview.policyVersion} · Generated {new Date(preview.evaluatedAt).toLocaleString()}</small>
        </section> : null}
      </div> : <p>Create your first segment. No synthetic or guessed customer data will be used.</p>}
      <p className="crm-segments__disclaimer">This screen does not publish audience memberships, export contact details, authorize provider campaigns, or override customer opt-outs.</p>
    </>}
  </Card>;
}
