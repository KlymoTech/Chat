import { useEffect, useState } from 'react';
import { Button, Field, Modal } from '@/components/ui';
import { api } from '@/lib/api';

export function WhatsAppTemplateComposer({ agentId, conversationId }: { agentId: string; conversationId: string }) {
  const [open, setOpen] = useState(false);
  const [templates, setTemplates] = useState<Awaited<ReturnType<typeof api.integrations.whatsapp.templates>>>([]);
  const [index, setIndex] = useState('');
  const [values, setValues] = useState<string[]>([]);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [sent, setSent] = useState(false);
  const template = index === '' ? undefined : templates[Number(index)];
  useEffect(() => {
    if (!open) return;
    let active = true;
    // Each open starts a fresh provider lookup and clears the previous recipient's form.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true); setError(''); setSent(false); setIndex(''); setValues([]); setConsent(false);
    void api.integrations.whatsapp.templates(agentId).then((items) => { if (active) setTemplates(items); })
      .catch((failure: unknown) => { if (active) setError(failure instanceof Error ? failure.message : 'Could not load templates'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [open, agentId]);
  const send = async () => {
    if (!template || !consent || busy) return;
    setBusy(true); setError('');
    try {
      await api.integrations.whatsapp.sendTemplate(conversationId, { name: template.name, language: template.language, parameters: values, consentConfirmed: true });
      setSent(true);
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Could not queue template'); }
    finally { setBusy(false); }
  };
  return <><Button variant="secondary" size="sm" onClick={() => setOpen(true)}>Send WhatsApp template</Button><Modal open={open} onClose={() => { if (!busy) setOpen(false); }} closeDisabled={busy} title="Send an approved WhatsApp template" description="Use an approved template to contact this customer outside the 24-hour service window. Meta messaging charges may apply." footer={<><Button variant="secondary" disabled={busy} onClick={() => setOpen(false)}>Close</Button>{!sent ? <Button disabled={loading || busy || !template || Boolean(template.unsupportedReason) || !consent || values.some((value) => !value.trim())} onClick={() => void send()}>{busy ? 'Queueing…' : 'Queue template'}</Button> : null}</>}>
    {error ? <p role="alert">{error}</p> : null}
    {sent ? <p role="status">Template queued. Check WhatsApp message activity for delivery confirmation.</p> : loading ? <p>Loading approved templates from Meta…</p> : <div className="whatsapp-form">
      <Field label="Approved template" htmlFor="wa-template"><select id="wa-template" value={index} disabled={busy} onChange={(event) => { setIndex(event.target.value); const next = templates[Number(event.target.value)]; setValues(next?.fields.map(() => '') ?? []); }}><option value="">Choose a template</option>{templates.map((item, i) => <option key={`${item.name}-${item.language}`} value={i}>{item.name} ({item.language})</option>)}</select></Field>
      {!templates.length ? <p>No approved templates found. Create a template in WhatsApp Manager and reopen this screen after approval.</p> : null}
      {template ? <><p style={{ whiteSpace: 'pre-wrap' }}>{template.preview}</p>{template.unsupportedReason ? <p role="alert">{template.unsupportedReason}</p> : template.fields.map((field, i) => <Field key={`${field.component}-${field.name}`} label={`${field.component} ${field.name}`} htmlFor={`wa-param-${i}`}><input id={`wa-param-${i}`} value={values[i] ?? ''} maxLength={1024} disabled={busy} onChange={(event) => setValues((items) => items.map((value, j) => i === j ? event.target.value : value))} /></Field>)}</> : null}
      <label><input type="checkbox" checked={consent} disabled={busy} onChange={(event) => setConsent(event.target.checked)} /> This customer opted in to receive these WhatsApp messages.</label>
    </div>}
  </Modal></>;
}
