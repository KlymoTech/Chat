import { Bot, ChevronDown, GripVertical, ListChecks, Plus, Save, Sparkles, Table2, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useToast, useWorkspace } from '@/components/providers';
import { Badge, Button, Card, EmptyState, PageLoader } from '@/components/ui';
import { api } from '@/lib/api';
import { botWorkflowApi, type BotWorkflowSave, type WorkflowFormat, type WorkflowPurpose, type WorkflowStep } from '@/lib/bot-workflow-api';
import { useApi } from '@/lib/use-api';
import './BotWorkflowBuilderPage.css';

const purposeLabels: Record<WorkflowPurpose, string> = { support: 'Support', lead_generation: 'Lead generation', education: 'Education' };
const blankStep = (index: number): WorkflowStep => ({ id: `step_${Date.now()}_${index}`, name: `Step ${index}`, triggerType: index === 1 ? 'command' : 'contains', triggerValue: index === 1 ? '/start' : '', messageFormat: 'text', message: '', buttons: [], table: null, template: null, enabled: true });
const purposeOf = (agent: { purpose?: WorkflowPurpose | null }) => agent.purpose ?? 'support';

export function BotWorkflowBuilderPage() {
  const { activeWorkspace } = useWorkspace();
  const { pushToast } = useToast();
  const agents = useApi(() => api.agents.list(), [activeWorkspace?.id]);
  const existing = useApi(() => botWorkflowApi.list(), [activeWorkspace?.id]);
  const [purpose, setPurpose] = useState<WorkflowPurpose>('support');
  const matchingAgents = useMemo(() => (agents.data ?? []).filter(agent => purposeOf(agent) === purpose), [agents.data, purpose]);
  const [agentId, setAgentId] = useState('');
  const [draft, setDraft] = useState<BotWorkflowSave>({ name: 'Customer conversation workflow', purpose: 'support', status: 'draft', steps: [blankStep(1)] });
  const [selectedStep, setSelectedStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const [templates, setTemplates] = useState<Awaited<ReturnType<typeof api.integrations.whatsapp.templates>>>([]);
  const [templateError, setTemplateError] = useState('');

  // Keep the selected bot valid as async workspace data and purpose filters change.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { if (!matchingAgents.some(agent => agent.id === agentId)) setAgentId(matchingAgents[0]?.id ?? ''); }, [agentId, matchingAgents]);
  useEffect(() => {
    if (!agentId) return;
    const saved = existing.data?.find(item => item.agentId === agentId);
    // Loading another bot intentionally replaces the editor draft with that bot's persisted workflow.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDraft(saved ? { name: saved.name, purpose: saved.purpose, status: saved.status, steps: saved.steps } : { name: `${purposeLabels[purpose]} workflow`, purpose, status: 'draft', steps: [blankStep(1)] });
    setSelectedStep(0);
    setTemplates([]); setTemplateError('');
    void api.integrations.whatsapp.templates(agentId).then(setTemplates).catch(error => setTemplateError(error instanceof Error ? error.message : 'WhatsApp templates could not be loaded'));
  }, [agentId, existing.data, purpose]);
  const step = draft.steps[selectedStep];
  const updateStep = (patch: Partial<WorkflowStep>) => setDraft(value => ({ ...value, steps: value.steps.map((item, index) => index === selectedStep ? { ...item, ...patch } : item) }));
  const save = async () => { if (!agentId || saving) return; setSaving(true); try { const value = await botWorkflowApi.save(agentId, draft); setDraft({ name: value.name, purpose: value.purpose, status: value.status, steps: value.steps }); existing.reload(); pushToast(value.status === 'active' ? 'Workflow published and active' : 'Workflow draft saved'); } catch (error) { pushToast(error instanceof Error ? error.message : 'Workflow could not be saved', 'error'); } finally { setSaving(false); } };
  if (agents.loading || existing.loading) return <PageLoader />;
  return <div className="page bot-workflow-page">
    <div className="page-heading page-heading--split"><div><span className="eyebrow">Conversation automation</span><h2>Bot workflow builder</h2><p>Decide which command or question triggers each response and control its WhatsApp format.</p></div><div><Badge tone={draft.status === 'active' ? 'success' : 'warning'}>{draft.status}</Badge><Button icon={Save} disabled={!agentId || saving || !draft.steps.length} onClick={() => void save()}>{saving ? 'Saving…' : 'Save workflow'}</Button></div></div>
    <Card className="workflow-scope-card"><div><label>Purpose<select value={purpose} onChange={event => { const next = event.target.value as WorkflowPurpose; setPurpose(next); setDraft(value => ({ ...value, purpose: next })); }}><option value="support">Support</option><option value="lead_generation">Lead generation</option><option value="education">Education</option></select><ChevronDown /></label><label>Bot<select value={agentId} onChange={event => setAgentId(event.target.value)}><option value="">Select a bot</option>{matchingAgents.map(agent => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select><ChevronDown /></label><label>Workflow name<input value={draft.name} onChange={event => setDraft(value => ({ ...value, name: event.target.value }))} /></label><label>Publishing<select value={draft.status} onChange={event => setDraft(value => ({ ...value, status: event.target.value as 'draft' | 'active' }))}><option value="draft">Draft — do not run</option><option value="active">Active — run before AI</option></select><ChevronDown /></label></div><p><Sparkles /> Active rules run in order before the bot’s normal AI answer. Use one fallback step only when every unmatched question should receive a fixed response.</p></Card>
    {!agentId ? <EmptyState icon={Bot} title={`No ${purposeLabels[purpose]} bot selected`} description="Create or select a bot with this purpose before building its message workflow." /> : <div className="workflow-builder-layout">
      <aside className="workflow-step-list"><div><strong>Workflow steps</strong><button type="button" onClick={() => { setDraft(value => ({ ...value, steps: [...value.steps, blankStep(value.steps.length + 1)] })); setSelectedStep(draft.steps.length); }}><Plus />Add</button></div>{draft.steps.map((item, index) => <button type="button" key={item.id} className={index === selectedStep ? 'is-active' : ''} onClick={() => setSelectedStep(index)}><GripVertical /><span><strong>{index + 1}. {item.name}</strong><small>{item.triggerType === 'fallback' ? 'Any unmatched message' : `${item.triggerType}: ${item.triggerValue || 'Not configured'}`}</small></span><Badge tone={item.enabled ? 'success' : 'neutral'}>{item.messageFormat}</Badge></button>)}</aside>
      {step ? <Card className="workflow-step-editor"><div className="workflow-step-heading"><div><span>Step {selectedStep + 1}</span><h3>{step.name}</h3></div><button type="button" aria-label="Delete step" onClick={() => { setDraft(value => ({ ...value, steps: value.steps.filter((_, index) => index !== selectedStep) })); setSelectedStep(Math.max(0, selectedStep - 1)); }}><Trash2 /></button></div>
        <div className="workflow-fields"><label>Step name<input value={step.name} onChange={event => updateStep({ name: event.target.value })} /></label><label className="workflow-toggle"><input type="checkbox" checked={step.enabled} onChange={event => updateStep({ enabled: event.target.checked })} />Enabled</label><label>When should this run?<select value={step.triggerType} onChange={event => updateStep({ triggerType: event.target.value as WorkflowStep['triggerType'], triggerValue: event.target.value === 'fallback' ? '' : step.triggerValue })}><option value="command">Exact command</option><option value="contains">Question contains</option><option value="fallback">Any unmatched message</option></select></label>{step.triggerType !== 'fallback' ? <label>{step.triggerType === 'command' ? 'Command' : 'Words or phrase'}<input value={step.triggerValue} placeholder={step.triggerType === 'command' ? '/courses' : 'refund status'} onChange={event => updateStep({ triggerValue: event.target.value })} /></label> : <p className="workflow-callout">Fallback runs only when no command or keyword step matches.</p>}</div>
        <fieldset className="workflow-format"><legend>Response format</legend>{(['text', 'buttons', 'table', 'template'] as WorkflowFormat[]).map(format => <label key={format} className={step.messageFormat === format ? 'is-selected' : ''}><input type="radio" checked={step.messageFormat === format} onChange={() => updateStep({ messageFormat: format })} /><span>{format === 'text' ? 'Text' : format === 'buttons' ? 'Quick buttons' : format === 'table' ? 'Table' : 'WhatsApp template'}</span></label>)}</fieldset>
        <label className="workflow-message">Message<textarea rows={5} value={step.message} placeholder="Write the response shown to the user" onChange={event => updateStep({ message: event.target.value })} /></label>
        {step.messageFormat === 'buttons' ? <ButtonEditor step={step} update={updateStep} /> : null}
        {step.messageFormat === 'table' ? <TableEditor step={step} update={updateStep} /> : null}
        {step.messageFormat === 'template' ? <div className="workflow-template-picker"><label>Approved WhatsApp template<select value={step.template ? `${step.template.name}|${step.template.language}` : ''} onChange={event => { const found = templates.find(item => `${item.name}|${item.language}` === event.target.value); updateStep({ template: found ? { name: found.name, language: found.language, preview: found.preview } : null, message: found?.preview ?? step.message }); }}><option value="">Choose template</option>{templates.map(item => <option key={`${item.name}|${item.language}`} value={`${item.name}|${item.language}`} disabled={Boolean(item.unsupportedReason)}>{item.name} ({item.language}){item.unsupportedReason ? ' — unsupported' : ''}</option>)}</select></label>{templateError ? <p role="alert">{templateError}</p> : !templates.length ? <p>No approved templates are available for this bot’s connected WhatsApp account.</p> : null}{step.template ? <pre>{step.template.preview}</pre> : null}</div> : null}
        <div className="workflow-preview"><small>Chat preview</small><strong>{step.message || 'Your response will appear here'}</strong>{step.messageFormat === 'buttons' ? <div>{step.buttons.map(button => <span key={button.id}>{button.title}</span>)}</div> : null}{step.messageFormat === 'table' && step.table ? <table><thead><tr>{step.table.columns.map(column => <th key={column}>{column}</th>)}</tr></thead><tbody>{step.table.rows.map((row, index) => <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table> : null}</div>
      </Card> : null}
    </div>}
  </div>;
}

function ButtonEditor({ step, update }: { step: WorkflowStep; update: (patch: Partial<WorkflowStep>) => void }) { return <div className="workflow-subeditor"><strong><ListChecks />Quick replies</strong>{step.buttons.map((button, index) => <label key={button.id}>Button {index + 1}<input maxLength={20} value={button.title} onChange={event => update({ buttons: step.buttons.map((item, i) => i === index ? { ...item, title: event.target.value } : item) })} /><button type="button" onClick={() => update({ buttons: step.buttons.filter((_, i) => i !== index) })}><Trash2 /></button></label>)}{step.buttons.length < 3 ? <button type="button" onClick={() => update({ buttons: [...step.buttons, { id: `choice_${step.buttons.length + 1}`, title: '' }] })}><Plus />Add button</button> : null}</div>; }
function TableEditor({ step, update }: { step: WorkflowStep; update: (patch: Partial<WorkflowStep>) => void }) { const columns = step.table?.columns.join(', ') ?? ''; const rows = step.table?.rows.map(row => row.join(', ')).join('\n') ?? ''; return <div className="workflow-subeditor"><strong><Table2 />Table</strong><label>Columns<input value={columns} placeholder="Course, Status" onChange={event => { const next = event.target.value.split(',').map(value => value.trim()).filter(Boolean); update({ table: { columns: next, rows: step.table?.rows ?? [] } }); }} /></label><label>Rows<textarea rows={4} value={rows} placeholder={'CMA, Active\nCPA, Active'} onChange={event => update({ table: { columns: step.table?.columns ?? [], rows: event.target.value.split('\n').filter(Boolean).map(line => line.split(',').map(value => value.trim())) } })} /></label></div>; }
