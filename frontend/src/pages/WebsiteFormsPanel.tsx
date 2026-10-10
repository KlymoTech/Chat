import { useCallback, useEffect, useMemo, useState } from 'react';
import { Copy, ExternalLink, FilePlus2, Plus, RefreshCw, Save, ShieldCheck, Trash2 } from 'lucide-react';
import { Button, Card } from '@/components/ui';
import { apiConfig, request } from '@/lib/api';
import './WebsiteFormsPanel.css';

type FieldKind = 'text' | 'email' | 'phone' | 'select' | 'radio' | 'checkbox' | 'date' | 'consent';
type Sensitivity = 'normal' | 'personal';
interface FormFieldCondition { field_key: string; equals: string }
interface FormField {
  key: string; label: string; kind: FieldKind; required: boolean; purpose: string;
  sensitivity: Sensitivity; retention_days: number; max_length: number; choices: string[];
  step?: number; condition?: FormFieldCondition | null;
}
interface FormDocument {
  title: string; submit_label: string; description: string; privacy_notice: string;
  fields: FormField[]; steps?: string[];
}
interface SiteForm {
  id: string; slug: string; agentId: string;
  draftVersion: number; publishedVersion: number | null; document: FormDocument;
}
interface AgentChoice { id: string; name: string; purpose?: string; status?: string }
interface Receipt { receiptId: string; leadId: string | null; createdAt: string; version: string }
const kinds: FieldKind[] = ['text', 'email', 'phone', 'select', 'radio', 'checkbox', 'date', 'consent'];
const field = (key: string, label: string, kind: FieldKind, required: boolean): FormField => ({
  key, label, kind, required, purpose: kind === 'consent'
    ? 'Permission to process this enquiry and respond'
    : 'Process and respond to this enquiry',
  sensitivity: 'personal', retention_days: 365,
  max_length: kind === 'text' ? 1000 : 300, choices: [],
  step: 1, condition: null,
});
const draftTemplate = (): FormDocument => ({
  title: 'Contact us', submit_label: 'Send enquiry',
  description: 'Tell us how we can help.',
  privacy_notice: 'We will use the details you provide to respond to this enquiry. This does not subscribe you to marketing.',
  steps: ['Your details'],
  fields: [
    field('name', 'Full name', 'text', true),
    field('email', 'Email address', 'email', true),
    field('message', 'Your message', 'text', true),
    field('processing_consent', 'I agree to processing of this enquiry', 'consent', true),
  ],
});
const say = (reason: unknown) => reason instanceof Error ? reason.message : 'Request failed. Please retry.';
const slugOk = (value: string) => /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value);
const fieldKeyOk = (value: string) => /^[a-z][a-z0-9_]*$/.test(value);

export function WebsiteFormsPanel({ workspaceId, onFormsChanged }: { workspaceId: string; onFormsChanged?: () => void }) {
  const [forms, setForms] = useState<SiteForm[]>([]);
  const [agents, setAgents] = useState<AgentChoice[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [draft, setDraft] = useState<FormDocument>(draftTemplate);
  const [newSlug, setNewSlug] = useState('');
  const [agentId, setAgentId] = useState('');
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const selected = forms.find((form) => form.id === selectedId) ?? null;
  const dirty = selected !== null && JSON.stringify(draft) !== JSON.stringify(selected.document);
  const availableAgents = useMemo(
    () => agents.filter((agent) => agent.purpose === 'lead_generation'),
    [agents],
  );

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [loaded, agentList] = await Promise.all([
        request<SiteForm[]>('/site-forms'),
        request<AgentChoice[]>('/agents'),
      ]);
      setForms(loaded);
      setAgents(agentList);
      setSelectedId('');
      setDraft(draftTemplate());
      setReceipts([]);
    } catch (reason) { setError(say(reason)); }
    finally { setLoading(false); }
  }, [workspaceId]);

  useEffect(() => { void load(); }, [load]);

  const select = (form: SiteForm | null) => {
    if (dirty && !window.confirm('Discard unsaved form changes?')) return;
    setSelectedId(form?.id ?? '');
    setDraft(form ? structuredClone(form.document) : draftTemplate());
    setAgentId(form?.agentId ?? '');
    setNewSlug(form?.slug ?? '');
    setReceipts([]);
    setError(''); setNotice('');
  };
  const changeField = (index: number, patch: Partial<FormField>) => {
    setDraft((current) => ({
      ...current,
      fields: current.fields.map((item, i) => i === index ? { ...item, ...patch } : item)
        .sort((left, right) => (left.step ?? 1) - (right.step ?? 1)),
    }));
  };
  const makeField = (kind: FieldKind) => {
    if (kind === 'consent' && draft.fields.some((item) => item.kind === 'consent')) return;
    const keys = new Set(draft.fields.map((item) => item.key));
    let next = draft.fields.length + 1;
    while (keys.has('field_' + next)) next++;
    const key = kind === 'consent' ? 'processing_consent' : 'field_' + next;
    const created = field(key, 'New field', kind, kind === 'consent');
    created.step = draft.steps?.length ?? 1;
    if (kind === 'select' || kind === 'radio') created.choices = ['Option A', 'Option B'];
    setDraft((current) => ({ ...current, fields: [...current.fields, created] }));
  };
  const addMarketingOptIn = () => {
    if (draft.fields.some((item) => item.key === 'marketing_opt_in')
      || draft.fields.length >= 30) return;
    const optional = field(
      'marketing_opt_in',
      'I agree to receive marketing emails',
      'checkbox',
      false,
    );
    optional.purpose = 'Receive optional marketing emails and updates from this organization';
    optional.step = draft.steps?.length ?? 1;
    setDraft((current) => ({ ...current, fields: [...current.fields, optional] }));
  };
  const addStep = () => {
    if ((draft.steps?.length ?? 1) >= 5 || draft.fields.length >= 30) return;
    setDraft((current) => {
      const steps = current.steps ?? ['Your details'];
      const keys = new Set(current.fields.map((item) => item.key));
      let n = current.fields.length + 1;
      while (keys.has('field_' + n)) n++;
      const nextField = field('field_' + n, 'New field', 'text', false);
      nextField.step = steps.length + 1;
      return { ...current, steps: [...steps, 'Step ' + (steps.length + 1)],
        fields: [...current.fields, nextField] };
    });
  };
  const removeLastStep = () => setDraft((current) => {
    const steps = current.steps ?? ['Your details'];
    if (steps.length <= 1) return current;
    return { ...current, steps: steps.slice(0, -1), fields: current.fields.map((item) =>
      item.step === steps.length ? { ...item, step: steps.length - 1 } : item) };
  });
  const stepNames = draft.steps ?? ['Your details'];
  const draftValid = (
    draft.title.trim().length > 0 && draft.privacy_notice.trim().length >= 10 &&
    stepNames.length >= 1 && stepNames.length <= 5 &&
    stepNames.every((label) => label.trim().length > 0 && label.trim().length <= 90) &&
    draft.fields.length >= 2 && draft.fields.length <= 30 &&
    draft.fields.every((item, index) => {
      const currentStep = item.step ?? 1;
      const prior = draft.fields.slice(0, index);
      const condition = item.condition;
      const controller = condition
        ? prior.find((candidate) => candidate.key === condition.field_key && !candidate.condition)
        : null;
      return fieldKeyOk(item.key)
        && Boolean(item.label.trim()) && item.purpose.trim().length >= 3
        && currentStep >= 1 && currentStep <= stepNames.length
        && (index === 0 || currentStep >= (draft.fields[index - 1]!.step ?? 1))
        && (item.kind !== 'consent' || (item.required && item.key === 'processing_consent'))
        && (item.kind === 'consent' || item.key !== 'processing_consent')
        && (item.key !== 'marketing_opt_in' || (
          item.kind === 'checkbox' && !item.required && !item.condition
          && item.label.toLowerCase().includes('marketing')
          && item.purpose.toLowerCase().includes('marketing')
          && draft.fields.some((candidate) =>
            candidate.kind === 'email' && candidate.required && !candidate.condition)
        ))
        && (item.kind !== 'checkbox' || item.key === 'marketing_opt_in'
          || !item.purpose.toLowerCase().includes('marketing'))
        && (item.kind === 'select' || item.kind === 'radio'
          ? item.choices.length > 0 && new Set(item.choices).size === item.choices.length
          : item.choices.length === 0)
        && (!condition || (
          Boolean(controller)
          && (controller!.step ?? 1) <= currentStep
          && (controller!.kind === 'select' || controller!.kind === 'radio'
            ? controller!.choices.includes(condition.equals)
            : controller!.kind === 'checkbox' && ['true', 'false'].includes(condition.equals))
          && item.kind !== 'consent'
          && !(item.required && (item.kind === 'email' || item.kind === 'phone'))
        ));
    }) &&
    stepNames.every((_, index) => draft.fields.some((item) => (item.step ?? 1) === index + 1)) &&
    new Set(draft.fields.map((item) => item.key)).size === draft.fields.length &&
    draft.fields.filter((item) => item.kind === 'consent').length === 1 &&
    draft.fields.some((item) => item.required && !item.condition
      && (item.kind === 'email' || item.kind === 'phone'))
  );
  const create = async () => {
    if (!draftValid || !slugOk(newSlug) || !agentId || busy) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const created = await request<SiteForm>('/site-forms', {
        method: 'POST', body: JSON.stringify({ slug: newSlug, agent_id: agentId, document: draft }),
      });
      setForms((current) => [created, ...current]);
      onFormsChanged?.();
      setSelectedId(created.id);
      setDraft(structuredClone(created.document));
      setNotice('Form saved as a private draft. Publish it when the assigned agent is active.');
    } catch (reason) { setError(say(reason)); }
    finally { setBusy(false); }
  };
  const save = async () => {
    if (!selected || !dirty || busy || !draftValid) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const saved = await request<SiteForm>('/site-forms/' + selected.id, {
        method: 'PUT', body: JSON.stringify({
          expected_version: selected.draftVersion, document: draft,
        }),
      });
      setForms((current) => current.map((entry) => entry.id === saved.id ? saved : entry));
      onFormsChanged?.();
      setDraft(structuredClone(saved.document));
      setNotice('Saved as revision ' + saved.draftVersion + '. The existing public revision remains unchanged.');
    } catch (reason) {
      setError(say(reason) + ' Your edits remain in this tab; reload only after preserving them.');
    } finally { setBusy(false); }
  };
  const publish = async (unpublish = false) => {
    if (!selected || dirty || busy) return;
    if (unpublish && !window.confirm('Stop accepting submissions on this public form? Historical leads remain stored.')) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const saved = await request<SiteForm>(
        '/site-forms/' + selected.id + (unpublish ? '/unpublish' : '/publish'),
        { method: 'POST', body: JSON.stringify({ expected_version: selected.draftVersion }) },
      );
      setForms((current) => current.map((entry) => entry.id === saved.id ? saved : entry));
      onFormsChanged?.();
      setNotice(unpublish ? 'Form is no longer public. Previous submissions remain available.'
        : 'Published revision ' + saved.publishedVersion + '. The public link is now active.');
    } catch (reason) { setError(say(reason)); }
    finally { setBusy(false); }
  };
  const receiptsForForm = async () => {
    if (!selected || busy) return;
    setBusy(true); setError('');
    try { setReceipts(await request<Receipt[]>('/site-forms/' + selected.id + '/submissions')); }
    catch (reason) { setError(say(reason)); }
    finally { setBusy(false); }
  };
  const url = selected && selected.publishedVersion !== null
    ? apiConfig.baseUrl.replace(/\/$/, '') + '/site-forms/public/' + workspaceId + '/' + selected.slug
    : '';

  return <Card>
    <div className="site-forms-heading">
      <div><h3>Website forms and lead capture</h3>
        <p>Build accessible enquiry forms linked to your existing Lead Generation Agent and CRM pipeline. Every published schema is pinned to an immutable revision.</p>
      </div>
      <Button variant="secondary" icon={RefreshCw} size="sm" disabled={busy || loading}
        onClick={() => { if (!dirty || window.confirm('Discard unsaved form edits?')) void load(); }}>Reload forms</Button>
    </div>
    {error ? <p className="form-error" role="alert">{error}</p> : null}
    {notice ? <p role="status" className="site-forms-notice">{notice}</p> : null}
    {loading ? <p>Loading website forms…</p> : <>
      <label>Choose a form
        <select value={selectedId} onChange={(event) => {
          select(forms.find((item) => item.id === event.target.value) ?? null);
        }}>
          <option value="">Create a new form…</option>
          {forms.map((item) => <option key={item.id} value={item.id}>
            {item.document.title} (/{item.slug}) · {item.publishedVersion ? 'published' : 'draft'}
          </option>)}
        </select>
      </label>
      {!selected ? <div className="site-forms-new">
        <label>Form URL slug
          <input required value={newSlug} placeholder="contact" maxLength={160}
            pattern="[a-z0-9]+(-[a-z0-9]+)*"
            onChange={(event) => setNewSlug(event.target.value)} />
        </label>
        <label>Lead Generation Agent
          <select value={agentId} onChange={(event) => setAgentId(event.target.value)}>
            <option value="">Select an existing agent…</option>
            {availableAgents.map((agent) => <option key={agent.id} value={agent.id}>
              {agent.name} · {agent.status === 'active' ? 'active' : 'activate before publishing'}
            </option>)}
          </select>
        </label>
        {availableAgents.length === 0 ? <p role="status">
          Create a Lead Generation Agent in Agents before creating this form. Existing agents are reused.
        </p> : null}
      </div> : <p className="site-forms-status">
        Draft v{selected.draftVersion} · Public {selected.publishedVersion ?? 'not published'}.
        {' '}Assigned agent: {agents.find((agent) => agent.id === selected.agentId)?.name ?? selected.agentId}
      </p>}
      <div className="site-forms-details">
        <label>Form title
          <input maxLength={180} value={draft.title}
            onChange={(event) => setDraft({ ...draft, title: event.target.value })} />
        </label>
        <label>Submit button text
          <input maxLength={80} value={draft.submit_label}
            onChange={(event) => setDraft({ ...draft, submit_label: event.target.value })} />
        </label>
        <label>Description
          <textarea maxLength={1000} rows={2} value={draft.description}
            onChange={(event) => setDraft({ ...draft, description: event.target.value })} />
        </label>
        <label>Privacy notice (shown to visitors)
          <textarea required maxLength={1000} rows={3} value={draft.privacy_notice}
            onChange={(event) => setDraft({ ...draft, privacy_notice: event.target.value })} />
        </label>
      </div>
      <div className="site-forms-steps">
        <h4>Form steps</h4>
        <p>Every step needs a heading and at least one field. Move fields by choosing a step below.</p>
        <div className="site-forms-step-labels">
          {stepNames.map((heading, index) => <label key={index}>Step {index + 1} heading
            <input maxLength={90} value={heading}
              onChange={(event) => setDraft((current) => ({
                ...current, steps: (current.steps ?? ['Your details']).map((name, i) =>
                  i === index ? event.target.value : name),
              }))}/>
          </label>)}
        </div>
        <div className="site-forms-actions">
          <Button variant="secondary" size="sm" icon={Plus}
            disabled={busy || stepNames.length >= 5 || draft.fields.length >= 30}
            onClick={addStep}>Add a step</Button>
          <Button variant="secondary" size="sm" disabled={busy || stepNames.length === 1}
            onClick={removeLastStep}>Remove last step</Button>
        </div>
      </div>
      <h4>Form fields</h4>
      <div className="site-forms-marketing-opt-in">
        <div>
          <strong>Optional email marketing consent</strong>
          <p>Marketing permission is separate from the mandatory enquiry-processing consent.
            The visitor must check the box; it is never preselected.</p>
        </div>
        <Button variant="secondary" size="sm" icon={Plus}
          disabled={busy || draft.fields.length >= 30
            || draft.fields.some((item) => item.key === 'marketing_opt_in')}
          onClick={addMarketingOptIn}>Add marketing opt-in</Button>
      </div>
      <p className="site-forms-subtitle">Fields require a stable key, explicit purpose, retention period and sensitivity. Sensitive and file fields require separate verified activation.</p>
      <div className="site-forms-fields">
        {draft.fields.map((item, index) => <fieldset className="site-forms-field" key={index}>
          <legend>Field {index + 1}: {item.label || item.key}</legend>
          <div className="site-forms-field-grid">
            <label>Form step
              <select value={item.step ?? 1}
                onChange={(event) => changeField(index, { step: Number(event.target.value) })}>
                {stepNames.map((heading, i) => <option key={i} value={i + 1}>{i + 1}. {heading}</option>)}
              </select>
            </label>
            <label>Stable key
              <input maxLength={60} pattern="[a-z][a-z0-9_]*" value={item.key}
                readOnly={item.key === 'marketing_opt_in'}
                onChange={(event) => changeField(index, { key: event.target.value })}/>
            </label>
            <label>Visitor label
              <input maxLength={120} value={item.label}
                onChange={(event) => changeField(index, { label: event.target.value })}/>
            </label>
            <label>Control type
              <select value={item.kind} disabled={item.key === 'marketing_opt_in'}
                onChange={(event) => {
                const kind = event.target.value as FieldKind;
                changeField(index, {
                  kind, required: kind === 'consent' ? true : item.required,
                  key: kind === 'consent' ? 'processing_consent' : item.key,
                  condition: kind === 'consent' ? null : item.condition,
                  choices: kind === 'select' || kind === 'radio' ? ['Option A', 'Option B'] : [],
                });
              }}>
                {kinds.map((kind) => <option key={kind} value={kind}>{kind}</option>)}
              </select>
            </label>
            {item.kind !== 'consent' && item.key !== 'marketing_opt_in'
              && !(item.required && (item.kind === 'email' || item.kind === 'phone')) &&
              <label>Display condition
                <select value={item.condition?.field_key ?? ''}
                  onChange={(event) => {
                    const source = draft.fields.slice(0, index).find((candidate) =>
                      candidate.key === event.target.value);
                    const equals = source?.kind === 'checkbox' ? 'true' : source?.choices[0] ?? '';
                    changeField(index, { condition: source
                      ? { field_key: source.key, equals } : null });
                  }}>
                  <option value="">Always visible</option>
                  {draft.fields.slice(0, index).filter((candidate) =>
                    !candidate.condition && (candidate.step ?? 1) <= (item.step ?? 1) &&
                    ['select', 'radio', 'checkbox'].includes(candidate.kind)
                  ).map((candidate) => <option key={candidate.key} value={candidate.key}>
                    {candidate.label} ({candidate.key})
                  </option>)}
                </select>
              </label>}
            {item.condition && <label>Show when choice equals
              <select value={item.condition.equals}
                onChange={(event) => changeField(index, {
                  condition: { ...item.condition!, equals: event.target.value },
                })}>
                {(draft.fields.find((candidate) => candidate.key === item.condition?.field_key)?.choices ??
                  ['true', 'false']).map((choice) => <option key={choice} value={choice}>{choice}</option>)}
              </select>
            </label>}
            <label>Purpose
              <input maxLength={180} value={item.purpose}
                onChange={(event) => changeField(index, { purpose: event.target.value })}/>
            </label>
            <label>Retention (days)
              <input type="number" min={1} max={3650} value={item.retention_days}
                onChange={(event) => changeField(index, { retention_days: Number(event.target.value) })}/>
            </label>
            <label>Classification
              <select value={item.sensitivity} onChange={(event) =>
                changeField(index, { sensitivity: event.target.value as Sensitivity })}>
                <option value="personal">Personal</option><option value="normal">Non-sensitive</option>
              </select>
            </label>
            <label>Maximum input length
              <input type="number" min={1} max={2000} value={item.max_length}
                onChange={(event) => changeField(index, { max_length: Number(event.target.value) })}/>
            </label>
            <label className="site-forms-checkbox">
              <input type="checkbox" checked={item.required} disabled={item.kind === 'consent' || item.key === 'marketing_opt_in'}
                onChange={(event) => changeField(index, { required: event.target.checked })}/>
              Required
            </label>
            {(item.kind === 'select' || item.kind === 'radio') &&
              <label className="site-forms-wide">Choices (one per line)
                <textarea rows={3} value={item.choices.join('\n')}
                  onChange={(event) => changeField(index, {
                    choices: event.target.value.split('\n').map((value) => value.trim()).filter(Boolean),
                  })}/>
              </label>}
          </div>
          <Button variant="secondary" size="sm" icon={Trash2}
            disabled={draft.fields.length <= 2 || busy || item.kind === 'consent'}
            onClick={() => setDraft((current) => ({
              ...current, fields: current.fields.filter((_, i) => i !== index),
            }))}>Remove field</Button>
        </fieldset>)}
      </div>
      <div className="site-forms-actions">
        <label>Add a field
          <select aria-label="New field type" id="site-form-new-kind" defaultValue="text">
            {kinds.map((kind) => <option key={kind} value={kind}>{kind}</option>)}
          </select>
        </label>
        <Button variant="secondary" size="sm" icon={Plus}
          disabled={busy || draft.fields.length >= 30}
          onClick={() => {
            const element = document.getElementById('site-form-new-kind') as HTMLSelectElement | null;
            makeField((element?.value as FieldKind) ?? 'text');
          }}>Add field</Button>
        {!selected ? <Button icon={FilePlus2} disabled={busy || !draftValid || !slugOk(newSlug) || !agentId}
          onClick={() => { void create(); }}>Create private form</Button> :
          <>
            <Button icon={Save} disabled={busy || !dirty || !draftValid}
              onClick={() => { void save(); }}>Save revision</Button>
            <Button variant="secondary" icon={ShieldCheck} disabled={busy || dirty ||
              selected.publishedVersion === selected.draftVersion}
              onClick={() => { void publish(); }}>Publish form</Button>
            <Button variant="secondary" disabled={busy || dirty || selected.publishedVersion === null}
              onClick={() => { void publish(true); }}>Unpublish safely</Button>
          </>}
      </div>
      {!draftValid ? <p role="status" className="site-forms-warning">
        A form needs valid step labels and ordering, unique field keys, a required email or phone,
        required processing consent and valid references to prior unconditional choices.
        Email marketing opt-in, when offered, must remain optional and clearly labeled.
      </p> : null}
      {url && <>
        <div className="site-forms-public">
          <strong>Published first-party form</strong>
          <a href={url} target="_blank" rel="noopener noreferrer">{url} <ExternalLink size={14}/></a>
          <Button variant="secondary" icon={Copy} size="sm"
            onClick={() => { void navigator.clipboard?.writeText(url); }}>Copy public URL</Button>
          <small>Add a button block with this URL in your existing visual page builder to link to the form.</small>
        </div>
        <div className="site-forms-receipts">
          <Button variant="secondary" size="sm" disabled={busy}
            onClick={() => { void receiptsForForm(); }}>Load submission receipts</Button>
          {receipts.map((entry) => <p key={entry.receiptId}>
            Receipt {entry.receiptId} · Form v{entry.version} · {new Date(entry.createdAt).toLocaleString()}.
            {' '}<a href="/leads">Review lead</a>
          </p>)}
        </div>
      </>}
    </>}
  </Card>;
}
