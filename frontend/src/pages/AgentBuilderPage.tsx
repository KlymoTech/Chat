import { KNOWLEDGE_UPLOAD_MAX_MB, knowledgeFileSizeError } from '@/lib/upload-limits';
import {
  AlertTriangle, ArrowLeft, BookOpen, Bot, BrainCircuit, Check, ChevronDown, Code2, Copy, Database,
  ExternalLink, File, FileText, Globe2, KeyRound, Link2, Mail, Plus, RefreshCw, Save, Settings2,
  ShieldCheck, SlidersHorizontal, Sparkles, Trash2, UploadCloud, WandSparkles, Zap,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type DragEvent, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { EducationKnowledgeScopeManager } from '@/components/education-knowledge-scope-manager';
import { ExtractionReviewModal } from '@/components/extraction-review-modal';
import { ChatWidget } from '@/components/chat-widget';
import { useToast } from '@/components/providers';
import { Badge, Button, Card, EmptyState, Field, Modal, PageLoader, Switch } from '@/components/ui';
import { api } from '@/lib/api';
import { apiErrorMessage } from '@/lib/api-error-message';
import { relativeTime } from '@/lib/format';
import { useApi } from '@/lib/use-api';
import { localizeAgentAppearance, supportedWidgetLanguages } from '@/lib/widget-localization';
import { AgentDeploymentPreview } from '@/pages/DeployPage';
import { WhatsAppMessageEditor } from '@/components/whatsapp-message-editor';
import { validWhatsAppSettings } from '@/lib/whatsapp-messages';
import type { Agent, AgentPatch, AgentPurpose, KnowledgeKind, KnowledgeSource } from '@/types';

const tabs = [
  { id: 'instructions', label: 'Instructions', icon: FileText },
  { id: 'knowledge', label: 'Knowledge', icon: BookOpen },
  { id: 'settings', label: 'Settings', icon: Settings2 },
  { id: 'embeddings', label: 'Embeddings', icon: BrainCircuit },
] as const;
type BuilderTab = typeof tabs[number]['id'];

const purposeLabels: Record<AgentPurpose, string> = {
  support: 'General / Support',
  lead_generation: 'Lead generation',
  education: 'Education',
};

function currentPurpose(agent: Agent): AgentPurpose {
  return agent.purpose ?? 'support';
}
function editableAgentFields(agent: Agent, saved: Agent): AgentPatch {
  const { name, description, instructions, status, purpose, tone, language, avatar, appearance, model, security } = agent;
  return { name, description, instructions, ...(status !== saved.status ? { status } : {}), purpose, tone, language, avatar, appearance, model, security };
}

export function AgentBuilderPage() {
  const { agentId = 'agent-northstar', tab = 'instructions' } = useParams();
  const agents = useApi(() => api.agents.list());
  const source = agents.data?.find((item) => item.id === agentId);
  const activeTab: BuilderTab = tabs.some((item) => item.id === tab) ? tab as BuilderTab : 'instructions';

  if (agents.loading || !source) {
    if (!agents.loading && agents.data && !source) return <div className="page"><Card><EmptyState icon={Bot} title="Agent not found" description="It may have been deleted or you may not have access." action={<Link to="/agents"><Button>Back to agents</Button></Link>} /></Card></div>;
    return <PageLoader />;
  }

  return <AgentBuilderWorkspace key={`${source.id}:${source.lastUpdated}`} initialAgent={source} allAgents={agents.data ?? []} activeTab={activeTab} reloadAgents={agents.reload} />;
}

function AgentBuilderWorkspace({ initialAgent, allAgents, activeTab, reloadAgents }: { initialAgent: Agent; allAgents: Agent[]; activeTab: BuilderTab; reloadAgents: () => void }) {
  const navigate = useNavigate(); const { pushToast } = useToast();
  const [agent, setAgent] = useState<Agent>(() => structuredClone(initialAgent)); const [dirty, setDirty] = useState(false); const [saving, setSaving] = useState(false); const [deleteOpen, setDeleteOpen] = useState(false);
  const update = (patch: AgentPatch) => { setAgent((current) => ({ ...current, ...patch })); setDirty(true); };
  const save = async () => { if (saving) return; if (!validWhatsAppSettings(agent.appearance.whatsapp)) { pushToast('Check the WhatsApp welcome message and reply structure before saving.', 'error'); return; } setSaving(true); try { const saved = await api.agents.update(agent.id, editableAgentFields(agent, initialAgent)); setAgent(saved); setDirty(false); reloadAgents(); pushToast('Agent changes saved'); } catch (reason) { pushToast(apiErrorMessage(reason, 'Could not save changes'), 'error'); } finally { setSaving(false); } };
  const remove = async () => { await api.agents.remove(agent.id); pushToast('Agent deleted'); navigate('/agents'); };
  const purpose = currentPurpose(agent);

  return <div className="builder-page">
    <div className="builder-agentbar"><Link to="/agents" className="back-link"><ArrowLeft /> All agents</Link><div className="agent-select-wrap"><span className="agent-avatar agent-avatar--small" style={{ background: agent.appearance.primaryColor }}>{agent.avatar}</span><select value={agent.id} onChange={(event) => navigate(`/agents/${event.target.value}/${activeTab}`)} aria-label="Select agent">{allAgents.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><ChevronDown /></div><Badge tone={agent.status === 'active' ? 'success' : 'warning'}>{agent.status}</Badge><Badge tone={purpose === 'lead_generation' ? 'brand' : purpose === 'education' ? 'purple' : 'neutral'}>{purposeLabels[purpose]}</Badge><div className="builder-agentbar__actions"><button onClick={() => navigate('/agents')}><Plus /> Create agent</button><button className="danger-link" onClick={() => setDeleteOpen(true)}><Trash2 /> Delete</button></div></div>
    <nav className="builder-tabs" aria-label="Agent configuration">{tabs.map(({ id, label, icon: Icon }) => <Link key={id} to={`/agents/${agent.id}/${id}`} className={activeTab === id ? 'is-active' : ''}><span><Icon /></span>{label}</Link>)}</nav>
    <div className={`builder-workspace builder-workspace--${activeTab}`}>
      <section className="builder-editor">
        {activeTab === 'instructions' ? <InstructionsPanel agent={agent} update={update} onSave={() => void save()} saving={saving} dirty={dirty} /> : null}
        {activeTab === 'knowledge' ? <KnowledgePanel agent={agent} onChanged={reloadAgents} /> : null}
        {activeTab === 'settings' ? <fieldset className="deploy-controls" disabled={saving}><SettingsPanel agent={agent} update={update} onSave={() => void save()} saving={saving} dirty={dirty} /></fieldset> : null}
        {activeTab === 'embeddings' ? <EmbeddingsPanel agent={agent} /> : null}
      </section>
      <BuilderAgentPreview agent={agent} liveKnowledgeTest={activeTab === 'knowledge'} />
    </div>
    <Modal open={deleteOpen} onClose={() => setDeleteOpen(false)} title="Delete this agent?" description="This action cannot be undone." size="sm" footer={<><Button variant="secondary" onClick={() => setDeleteOpen(false)}>Cancel</Button><Button variant="danger" icon={Trash2} onClick={() => void remove()}>Delete forever</Button></>}><p className="modal-warning"><AlertTriangle /> All deployments of <strong>{agent.name}</strong> will stop responding immediately.</p></Modal>
  </div>;
}

const channelNames: Record<string, string> = { website: 'Website widget', whatsapp: 'WhatsApp', instagram: 'Instagram', facebook: 'Facebook / Meta', slack: 'Slack', teams: 'Microsoft Teams', api: 'Developer API', notion: 'Notion', zapier: 'Zapier' };

function BuilderAgentPreview({ agent, liveKnowledgeTest = false }: { agent: Agent; liveKnowledgeTest?: boolean }) {
  const channel = agent.appearance.deploymentChannel ?? 'website';
  const [testSession, setTestSession] = useState(0);
  if (liveKnowledgeTest) return <aside className="widget-preview agent-template-preview knowledge-test-preview">
    <div className="preview-toolbar"><span><i className="status-dot status-dot--success" /> Live knowledge test</span><button type="button" onClick={() => setTestSession((value) => value + 1)}><RefreshCw /> New test</button></div>
    <div className="knowledge-test-preview__intro"><BrainCircuit /><div><strong>Ask about your uploaded material</strong><small>Answers stream from the real agent endpoint and show citations from indexed sources.</small></div></div>
    <div className="deploy-preview__stage deploy-preview__stage--mobile"><ChatWidget key={`${agent.id}:${testSession}`} agent={agent} embedded /></div>
    <p>Only sources marked Ready are searchable. Untrained sources stop contributing to future answers.</p>
  </aside>;
  return <aside className="widget-preview agent-template-preview">
    <div className="preview-toolbar"><span><i className="status-dot status-dot--success" /> {channelNames[channel] ?? 'Website widget'} preview</span></div>
    <div className="deploy-preview__stage deploy-preview__stage--mobile"><AgentDeploymentPreview agent={agent} integrationId={channel} /></div>
    <p>The duplicate keeps this channel template in its workspace.</p>
  </aside>;
}

interface PanelProps { agent: Agent; update: (patch: AgentPatch) => void; onSave: () => void; saving: boolean; dirty: boolean }

function InstructionsPanel({ agent, update, onSave, saving, dirty }: PanelProps) {
  const maxLength = 8000;
  return <div className="editor-inner">
    <div className="builder-heading"><span className="builder-heading__icon"><FileText /></span><div><h2>Instructions</h2><p>Define the job, boundaries, and voice of your AI agent.</p></div></div>
    <div className="hint-card"><WandSparkles /><div><strong>Write instructions like a great onboarding brief</strong><p>Give the agent a clear role, trusted sources, response style, and what to do when it cannot answer.</p></div><button>View examples <ExternalLink /></button></div>
    <Card className="editor-card"><div className="editor-card__heading"><div><h3>Core instructions</h3><p>These rules guide every response.</p></div><Badge tone="brand">Always active</Badge></div><textarea className="instructions-editor" value={agent.instructions} onChange={(event) => update({ instructions: event.target.value.slice(0, maxLength) })} placeholder="You are a helpful expert…" rows={17} /><div className="editor-footer"><span>{agent.instructions.length.toLocaleString()} / {maxLength.toLocaleString()}</span><span><Check /> Auto-saved locally while editing</span></div></Card>
    <Card className="behavior-card"><div className="editor-card__heading"><div><h3>Voice & language</h3><p>The selected language controls every visitor-facing label, starter question, and AI response.</p></div></div><div className="two-fields"><Field label="Response tone" htmlFor="tone"><select id="tone" value={agent.tone} onChange={(event) => update({ tone: event.target.value as Agent['tone'] })}><option value="professional">Professional</option><option value="friendly">Friendly</option><option value="concise">Concise</option><option value="empathetic">Empathetic</option><option value="playful">Playful</option></select></Field><Field label="Primary language" htmlFor="language"><select id="language" value={agent.language} onChange={(event) => { const language = event.target.value; update({ language, appearance: localizeAgentAppearance(agent.appearance, language) }); }}>{supportedWidgetLanguages.map((language) => <option key={language}>{language}</option>)}</select></Field></div></Card>
    <SaveBar dirty={dirty} saving={saving} onSave={onSave} />
  </div>;
}

function SaveBar({ dirty, saving, onSave }: { dirty: boolean; saving: boolean; onSave: () => void }) {
  return <div className={`save-bar ${dirty ? 'is-dirty' : ''}`}><span>{dirty ? 'You have unpublished changes' : <><Check /> All changes saved</>}</span><Button icon={Save} disabled={!dirty || saving} onClick={onSave}>{saving ? 'Saving…' : 'Save changes'}</Button></div>;
}

function KnowledgePanel({ agent, onChanged }: { agent: Agent; onChanged: () => void }) {
  const result = useApi(() => api.knowledge.list(agent.id), [agent.id]); const { pushToast } = useToast(); const [addOpen, setAddOpen] = useState(false); const [selected, setSelected] = useState<string[]>([]); const [reviewSource, setReviewSource] = useState<KnowledgeSource | null>(null); const [untraining, setUntraining] = useState<KnowledgeSource[]>([]); const [removing, setRemoving] = useState(false);
  const reloadSources = result.reload;
  const processingSources = result.data?.some((source) => source.status === 'processing');
  useEffect(() => { if (!processingSources) return; const timer = window.setInterval(reloadSources, 5000); return () => window.clearInterval(timer); }, [processingSources, reloadSources]);
  const confirmUntrain = async () => {
    if (!untraining.length || removing) return;
    setRemoving(true);
    try {
      await api.knowledge.untrain(untraining.map((source) => source.id));
      const removedIds = new Set(untraining.map((source) => source.id));
      setSelected((current) => current.filter((id) => !removedIds.has(id)));
      pushToast(untraining.length === 1 ? `${untraining[0]!.name} untrained` : `${untraining.length} sources untrained`);
      setUntraining([]); await result.reload(); onChanged();
    } catch (reason) { pushToast(apiErrorMessage(reason, 'Could not untrain the selected knowledge'), 'error'); }
    finally { setRemoving(false); }
  };
  const selectedSources = (result.data ?? []).filter((source) => selected.includes(source.id));
  return <div className="editor-inner editor-inner--wide"><div className="builder-heading builder-heading--actions"><span className="builder-heading__icon"><BookOpen /></span><div><h2>Knowledge</h2><p>Give your agent reliable information to ground every answer.</p></div><Button icon={Plus} onClick={() => setAddOpen(true)}>Add source</Button></div>
    <div className="knowledge-stats"><Card><span><Database /></span><div><strong>{result.data?.length ?? 0}</strong><small>Sources</small></div></Card><Card><span><FileText /></span><div><strong>{result.data?.reduce((sum, item) => sum + item.chunks, 0) ?? 0}</strong><small>Knowledge chunks</small></div></Card><Card><span><Check /></span><div><strong>{result.data?.filter((item) => item.status === 'ready').length ?? 0}</strong><small>Ready to answer</small></div></Card></div>
    <Card className="knowledge-table-card"><div className="table-toolbar"><div><h3>Sources</h3><p>Content is automatically chunked and indexed.</p></div><div>{selectedSources.length ? <Button variant="danger" size="sm" icon={Trash2} onClick={() => setUntraining(selectedSources)}>Untrain {selectedSources.length}</Button> : null}<Button variant="secondary" size="sm" icon={Link2} onClick={() => setAddOpen(true)}>Import from source</Button><Button size="sm" icon={Plus} onClick={() => setAddOpen(true)}>Create</Button></div></div>
      {result.loading ? <div className="table-loading">Loading sources…</div> : result.data?.length ? <div className="responsive-table"><table><thead><tr><th><input type="checkbox" aria-label="Select all sources" checked={selected.length === result.data.length && result.data.length > 0} onChange={(event) => setSelected(event.target.checked ? result.data!.map((item) => item.id) : [])} /></th><th>Source</th><th>Status</th><th>Type</th><th>Chunks</th><th>Updated</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>{result.data.map((source) => <tr key={source.id}><td><input type="checkbox" aria-label={`Select ${source.name}`} checked={selected.includes(source.id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, source.id] : current.filter((id) => id !== source.id))} /></td><td><span className={`source-icon source-icon--${source.kind}`}>{source.kind === 'file' ? <File /> : source.kind === 'text' ? <FileText /> : <Globe2 />}</span><span><strong>{source.name}</strong><small>{source.url ?? source.sizeLabel}</small></span></td><td><Badge tone={source.status === 'ready' ? 'success' : source.status === 'failed' ? 'danger' : 'purple'}><i className="status-dot" /> {source.status}</Badge></td><td className="capitalize">{source.kind}</td><td>{source.chunks}</td><td>{relativeTime(source.updatedAt)}</td><td><button className="icon-button danger-hover" onClick={() => setUntraining([source])} aria-label={`Untrain ${source.name}`}><Trash2 /></button></td></tr>)}</tbody></table></div> : <EmptyState icon={BookOpen} title="No knowledge yet" description="Upload a file, add a webpage, or write content directly." action={<Button icon={Plus} onClick={() => setAddOpen(true)}>Add your first source</Button>} />}
    </Card>
    {result.data?.filter((source) => source.status === 'needs_review' || source.extractionAvailable).map((source) => <Card key={source.id}><strong>{source.name}</strong><p>{source.status === 'needs_review' ? `Extraction review required: ${source.extractionIssueCount ?? 0} unresolved issues. This file is not searchable until approved.` : 'Source evidence and extraction reports are available.'}</p><Button variant="secondary" onClick={() => setReviewSource(source)}>{source.status === 'needs_review' ? 'Review source pages' : 'View extraction evidence'}</Button></Card>)}
    {currentPurpose(agent) === 'education' ? <EducationKnowledgeScopeManager agentId={agent.id} sources={result.data ?? []} /> : null}
    {addOpen ? <KnowledgeModal agentId={agent.id} education={currentPurpose(agent) === 'education'} onClose={() => setAddOpen(false)} onCreated={() => { setAddOpen(false); result.reload(); onChanged(); pushToast('Knowledge source added'); }} /> : null}
    {reviewSource && <ExtractionReviewModal source={reviewSource} onClose={() => setReviewSource(null)} onApproved={(message) => { setReviewSource(null); result.reload(); pushToast(message ?? 'Extraction approved; indexing started'); }} />}
    <Modal open={untraining.length > 0} onClose={() => { if (!removing) setUntraining([]); }} closeDisabled={removing} title={untraining.length === 1 ? 'Untrain this source?' : `Untrain ${untraining.length} sources?`} description="This removes the selected material from future retrieval and cannot be undone." size="sm" footer={<><Button variant="secondary" disabled={removing} onClick={() => setUntraining([])}>Cancel</Button><Button variant="danger" icon={Trash2} disabled={removing} onClick={() => void confirmUntrain()}>{removing ? 'Untraining…' : 'Untrain knowledge'}</Button></>}><div className="knowledge-untrain-summary"><AlertTriangle /><div><strong>{untraining.reduce((sum, source) => sum + source.chunks, 0).toLocaleString()} indexed chunks will be removed</strong><p>{untraining.map((source) => source.name).join(', ')}</p><small>The original upload and extraction artifacts will also be securely purged.</small></div></div></Modal>
  </div>;
}

function KnowledgeModal({ agentId, education, onClose, onCreated }: { agentId: string; education: boolean; onClose: () => void; onCreated: () => void }) {
  const [kind, setKind] = useState<KnowledgeKind>('file'); const [name, setName] = useState(''); const [value, setValue] = useState(''); const [file, setFile] = useState<File | null>(null); const [saving, setSaving] = useState(false); const [error, setError] = useState(''); const inputRef = useRef<HTMLInputElement>(null);
  const fileName = file?.name ?? '';
  const valid = kind === 'file' ? Boolean(file) : Boolean(value.trim());
  const submit = async (event?: FormEvent) => { event?.preventDefault(); if (!valid) return; setSaving(true); setError(''); try { await api.knowledge.add(agentId, { kind, name: name.trim() || fileName || (kind === 'text' ? 'Custom knowledge' : value), ...(kind === 'file' && file ? { file } : kind === 'text' ? { content: value } : kind === 'url' || kind === 'sitemap' ? { url: value } : {}) }); onCreated(); } catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to add this source.'); } finally { setSaving(false); } };
  const chooseFile = (files: FileList | null) => { const selected = files?.[0]; if (!selected) return; const sizeError = knowledgeFileSizeError(selected); if (sizeError) { setFile(null); setError(sizeError); return; } setError(''); setFile(selected); setName(selected.name); };
  const drop = (event: DragEvent) => { event.preventDefault(); chooseFile(event.dataTransfer.files); };
  const options: Array<{ id: KnowledgeKind; icon: typeof UploadCloud; label: string }> = [{ id: 'file', icon: UploadCloud, label: 'File upload' }, { id: 'url', icon: Link2, label: 'Web page' }, { id: 'sitemap', icon: Globe2, label: 'Sitemap' }, { id: 'text', icon: FileText, label: 'Write text' }];
  if (education) return <Modal open onClose={onClose} title="Add course knowledge" description="Education sources require an explicit course audience before processing." size="lg" footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Link className="button button--primary button--md" to={`/education/knowledge?agentId=${encodeURIComponent(agentId)}`} onClick={onClose}>Open course knowledge</Link></>}><div className="hint-card"><ShieldCheck /><div><strong>Choose the course, curriculum, paper, and batch first</strong><p>This prevents private material from entering an unrestricted knowledge pool. The course knowledge workspace uploads, reviews, indexes, and publishes the source without training a separate model.</p></div></div></Modal>;
  return <Modal open onClose={onClose} title="Add knowledge" description="Choose how you want to teach this agent." size="lg" footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button disabled={!valid || saving} onClick={() => void submit()}>{saving ? 'Processing…' : 'Add source'}</Button></>}><form onSubmit={(event) => void submit(event)}><div className="source-tabs">{options.map(({ id, icon: Icon, label }) => <button type="button" key={id} className={kind === id ? 'is-active' : ''} onClick={() => { setKind(id); setError(''); }}><Icon />{label}</button>)}</div>
    {error ? <div className="form-error" role="alert">{error}</div> : null}
    {kind === 'file' ? <div className={`drop-zone ${fileName ? 'has-file' : ''}`} onDragOver={(event) => event.preventDefault()} onDrop={drop} onClick={() => inputRef.current?.click()}><input ref={inputRef} type="file" hidden accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.tif,.tiff" onChange={(event) => chooseFile(event.target.files)} />{fileName ? <><Check /><strong>{fileName}</strong><small>Ready to upload</small></> : <><UploadCloud /><strong>Drop a file here, or click to browse</strong><small>PDF, DOCX, text, PNG, JPEG, or TIFF · up to {KNOWLEDGE_UPLOAD_MAX_MB} MB</small></>}</div> : <><Field label="Source name (optional)" htmlFor="source-name"><input id="source-name" value={name} onChange={(event) => setName(event.target.value)} placeholder={kind === 'text' ? 'e.g. Returns policy' : 'e.g. Help center'} /></Field><Field label={kind === 'text' ? 'Knowledge content' : kind === 'sitemap' ? 'Sitemap URL' : 'Page URL'} htmlFor="source-value" hint={kind === 'sitemap' ? 'We will securely crawl pages listed in this sitemap.' : undefined}>{kind === 'text' ? <textarea id="source-value" rows={8} value={value} onChange={(event) => setValue(event.target.value)} placeholder="Paste or write reliable information…" /> : <input id="source-value" type="url" value={value} onChange={(event) => setValue(event.target.value)} placeholder="https://example.com/docs" />}</Field></>}
  </form></Modal>;
}

function SettingsPanel({ agent, update, onSave, saving, dirty }: PanelProps) {
  const appearance = (patch: Partial<Agent['appearance']>) => update({ appearance: { ...agent.appearance, ...patch } });
  const model = (patch: Partial<Agent['model']>) => update({ model: { ...agent.model, ...patch } });
  const security = (patch: Partial<Agent['security']>) => update({ security: { ...agent.security, ...patch } });
  const purpose = currentPurpose(agent);
  const changePurpose = (next: AgentPurpose) => update({ purpose: next, ...(next === 'education' ? { status: 'draft' as const } : {}) });
  return <div className="editor-inner editor-inner--settings"><div className="builder-heading"><span className="builder-heading__icon"><Settings2 /></span><div><h2>Agent settings</h2><p>Control identity, purpose, intelligence, appearance, and safeguards.</p></div></div>
    <SettingsSection icon={Bot} title="Identity & purpose" description="How this agent appears and which business workflow it is allowed to enter."><div className="settings-form-grid"><Field label="Agent name" htmlFor="settings-name"><input id="settings-name" value={agent.name} onChange={(event) => update({ name: event.target.value })} /></Field><Field label="Description" htmlFor="settings-description"><input id="settings-description" value={agent.description} onChange={(event) => update({ description: event.target.value })} /></Field><Field label="Agent purpose" htmlFor="settings-purpose" hint="Purpose controls business workflow routing, not just starter text."><select id="settings-purpose" value={purpose} onChange={(event) => changePurpose(event.target.value as AgentPurpose)}><option value="support">General / Support</option><option value="lead_generation">Lead generation</option><option value="education">Education</option></select></Field></div>{purpose === 'education' ? <div className="hint-card"><BookOpen /><div><strong>Education safety mode</strong><p>This Agent stays in draft until Course, Batch, Student, and Enrollment authorization is configured. Private course knowledge must never run through the unrestricted general path.</p></div></div> : null}</SettingsSection>
    {agent.appearance.deploymentChannel === 'whatsapp' ? <>
      <WhatsAppMessageEditor agent={agent} section="welcome" onChange={appearance} />
      <WhatsAppMessageEditor agent={agent} section="format" onChange={appearance} />
      <Link className="inline-link" to={`/deploy?agentId=${agent.id}`}>WhatsApp number, activation, and sharing <ExternalLink /></Link>
    </> : <SettingsSection icon={SlidersHorizontal} title="Widget appearance" description="Make the customer-facing experience feel like your product."><div className="settings-form-grid settings-form-grid--appearance"><Field label="Primary color" htmlFor="primary-color"><div className="color-input"><input id="primary-color" type="color" value={agent.appearance.primaryColor} onChange={(event) => appearance({ primaryColor: event.target.value })} /><input value={agent.appearance.primaryColor} onChange={(event) => appearance({ primaryColor: event.target.value })} aria-label="Primary color hex" /></div></Field><Field label="Widget placement" htmlFor="position"><select id="position" value={agent.appearance.position} onChange={(event) => appearance({ position: event.target.value as Agent['appearance']['position'] })}><option value="bottom-right">Bottom right</option><option value="bottom-left">Bottom left</option></select></Field><Field label="Hero heading" htmlFor="welcome-title"><input id="welcome-title" value={agent.appearance.welcomeTitle} onChange={(event) => appearance({ welcomeTitle: event.target.value })} /></Field><Field label="Message placeholder" htmlFor="placeholder"><input id="placeholder" value={agent.appearance.placeholder} onChange={(event) => appearance({ placeholder: event.target.value })} /></Field></div><Field label="Greeting message" htmlFor="welcome-message"><input id="welcome-message" value={agent.appearance.welcomeMessage} onChange={(event) => appearance({ welcomeMessage: event.target.value })} /></Field><Field label="Conversation starters" hint="One question per line." htmlFor="starters"><textarea id="starters" rows={4} value={agent.appearance.suggestedQuestions.join('\n')} onChange={(event) => appearance({ suggestedQuestions: event.target.value.split('\n').slice(0, 5) })} /></Field><Switch label="Show Northstar branding" description="Display a small “Powered by Northstar AI” label." checked={agent.appearance.showBranding} onChange={(value) => appearance({ showBranding: value })} /></SettingsSection>}
    <SettingsSection icon={BrainCircuit} title="LLM connection" description="NVIDIA Nemotron powers generation and reasoning."><div className="provider-banner"><span className="nvidia-mark">N</span><div><strong>NVIDIA AI Endpoints</strong><small><i className="status-dot status-dot--success" /> Connected securely through the server</small></div><Badge tone="success">Connected</Badge></div><div className="settings-form-grid"><Field label="Model" htmlFor="model"><select id="model" value={agent.model.model} onChange={(event) => model({ model: event.target.value })}><option value="nvidia/nemotron-3-ultra-550b-a55b">Nemotron 3 Ultra 550B</option></select></Field><Field label={`Creativity · ${agent.model.temperature.toFixed(1)}`} htmlFor="temperature"><input id="temperature" type="range" min="0" max="1.5" step="0.1" value={agent.model.temperature} onChange={(event) => model({ temperature: Number(event.target.value) })} /></Field><Field label="Rerank candidates" htmlFor="rerank-candidates" hint="More candidates improve recall but add database work."><input id="rerank-candidates" type="number" min="10" max="100" value={agent.model.rerankCandidates ?? 60} onChange={(event) => model({ rerankCandidates: Number(event.target.value) })} /></Field><Field label="Final context chunks" htmlFor="final-context-chunks"><input id="final-context-chunks" type="number" min="2" max="20" value={agent.model.finalContextChunks ?? 8} onChange={(event) => model({ finalContextChunks: Number(event.target.value) })} /></Field></div><div className="settings-switches"><Switch label="Reasoning mode" description="Let Nemotron reason through complex requests before answering." checked={agent.model.enableThinking} onChange={(value) => model({ enableThinking: value })} /><Switch label="Citations" description="Link answers back to connected sources when available." checked={agent.model.citationMode !== 'off'} onChange={(value) => model({ citationMode: value ? 'when-available' : 'off' })} /></div></SettingsSection>
    <SettingsSection icon={Globe2} title="Knowledge boundaries" description="Control when this agent may use the public web and which topics it must refuse."><Field label="Answer fallback" htmlFor="web-fallback" hint="Internal approved knowledge is tried first, followed by the selected fallback."><select id="web-fallback" value={agent.security.webFallback ?? 'public'} onChange={(event) => security({ webFallback: event.target.value as Agent['security']['webFallback'] })}><option value="off">Use approved knowledge only</option><option value="related_only">Use approved knowledge and allowlisted websites</option><option value="public">Answer broadly using the public web and general AI knowledge</option></select></Field>{agent.security.webFallback === 'related_only' ? <Field label="Allowed web domains" htmlFor="web-domains" hint="One domain per line."><textarea id="web-domains" rows={3} value={(agent.security.webAllowedDomains ?? []).join('\n')} onChange={(event) => security({ webAllowedDomains: event.target.value.split('\n').map((value) => value.trim()).filter(Boolean) })} placeholder="docs.example.com" /></Field> : null}<Field label="Questions this bot must not answer" htmlFor="blocked-topics" hint="One topic or phrase per line. Matching questions are refused before retrieval."><textarea id="blocked-topics" rows={4} value={(agent.security.blockedTopics ?? []).join('\n')} onChange={(event) => security({ blockedTopics: event.target.value.split('\n').map((value) => value.trim()).filter(Boolean) })} placeholder="medical diagnosis\nlegal advice\ncompetitor pricing" /></Field></SettingsSection>
    <SettingsSection icon={Zap} title="Rate limiting" description="Protect availability and control inference usage."><div className="radio-cards"><label className={agent.security.rateLimitPerMinute === 0 ? 'is-selected' : ''}><input type="radio" checked={agent.security.rateLimitPerMinute === 0} onChange={() => security({ rateLimitPerMinute: 0 })} /><strong>No limit</strong><small>Best for private, trusted deployments.</small></label><label className={agent.security.rateLimitPerMinute > 0 ? 'is-selected' : ''}><input type="radio" checked={agent.security.rateLimitPerMinute > 0} onChange={() => security({ rateLimitPerMinute: 30 })} /><strong>Per-visitor limit</strong><small>Reduce abusive or automated traffic.</small></label></div>{agent.security.rateLimitPerMinute > 0 ? <Field label="Messages per minute" htmlFor="rate-limit"><input id="rate-limit" type="number" min="1" max="300" value={agent.security.rateLimitPerMinute} onChange={(event) => security({ rateLimitPerMinute: Number(event.target.value) })} /></Field> : null}</SettingsSection>
    <SettingsSection icon={ShieldCheck} title="Privacy & handoff" description="Choose what is collected and when people step in."><div className="settings-switches"><Switch label="Email transcripts" description="Offer visitors an emailed copy of their conversation." checked={agent.security.collectEmail} onChange={(value) => security({ collectEmail: value })} /><Switch label="Track knowledge gaps" description="Flag questions with low-confidence or unsupported answers." checked onChange={() => undefined} /><Switch label="Mask sensitive data" description="Redact common credentials and payment details from logs." checked={agent.security.maskSensitiveData} onChange={(value) => security({ maskSensitiveData: value })} /></div><div className="agent-id-row"><span><KeyRound /><span><strong>Agent ID</strong><small>Use this immutable ID in API requests.</small></span></span><code>{agent.id}</code><CopyButton value={agent.id} /></div></SettingsSection>
    <SaveBar dirty={dirty} saving={saving} onSave={onSave} />
  </div>;
}

function SettingsSection({ icon: Icon, title, description, children }: { icon: typeof Bot; title: string; description: string; children: React.ReactNode }) { return <Card className="settings-section"><div className="settings-section__heading"><span><Icon /></span><div><h3>{title}</h3><p>{description}</p></div></div><div className="settings-section__body">{children}</div></Card>; }

function EmbeddingsPanel({ agent }: { agent: Agent }) {
  const [active, setActive] = useState<'script' | 'react' | 'api'>('script'); const { pushToast } = useToast();
  const snippets = useMemo(() => ({
    script: `<script src="${window.location.origin}/widget.js"\n  data-agent-id="${agent.publicId}"\n  async></script>`,
    react: `import { NorthstarWidget } from '@northstar-ai/react';\n\n<NorthstarWidget agentId="${agent.id}" />`,
    api: `curl -X POST https://api.northstar.ai/v1/chat/stream \\\n  -H "Authorization: Bearer $NORTHSTAR_API_KEY" \\\n  -H "Content-Type: application/json" \\\n  -d '{"agent_id":"${agent.id}","message":"Hello"}'`,
  }), [agent.id, agent.publicId]);
  if (agent.appearance.deploymentChannel === 'whatsapp') return <div className="editor-inner editor-inner--wide"><Card className="settings-section"><div className="settings-section__heading"><div><h3>WhatsApp deployment</h3><p>Manage the assigned number, welcome message, reply structure, and activation in Deploy.</p></div></div><div className="settings-section__body"><Link className="button button--primary" to={`/deploy?agentId=${agent.id}`}>Open WhatsApp settings <ExternalLink /></Link></div></Card></div>;
  return <div className="editor-inner editor-inner--wide"><div className="builder-heading"><span className="builder-heading__icon"><BrainCircuit /></span><div><h2>Embeddings & deployment</h2><p>Put this agent wherever your customers need an answer.</p></div></div>
    <div className="deploy-choice-grid"><Card className="deploy-choice is-active"><span><Code2 /></span><Badge tone="success">Ready</Badge><h3>Web widget</h3><p>A responsive chat bubble that inherits your appearance settings.</p></Card><Card className="deploy-choice"><span><Zap /></span><Badge>API</Badge><h3>Custom experience</h3><p>Stream answers into your app with the REST API or SDK.</p></Card><Card className="deploy-choice"><span><Mail /></span><Badge tone="purple">Beta</Badge><h3>Connected channels</h3><p>Bring your agent to Slack, WhatsApp, and support tools.</p></Card></div>
    <Card className="code-card"><div className="code-card__heading"><div><h3>Install your agent</h3><p>Copy one snippet. Updates publish without reinstalling.</p></div><div className="code-tabs">{(['script', 'react', 'api'] as const).map((item) => <button key={item} className={active === item ? 'is-active' : ''} onClick={() => setActive(item)}>{item === 'script' ? 'JavaScript' : item === 'react' ? 'React' : 'REST API'}</button>)}</div></div><div className="code-block"><pre><code>{snippets[active]}</code></pre><CopyButton value={snippets[active]} onCopied={() => pushToast('Code copied')} /></div></Card>
    <Card className="domain-card"><div className="editor-card__heading"><div><h3>Allowed domains</h3><p>Only these websites can load your published widget.</p></div><Badge tone="success"><ShieldCheck /> Protected</Badge></div>{agent.security.allowedDomains.length ? <div className="domain-list">{agent.security.allowedDomains.map((domain) => <span key={domain}><Globe2 /> {domain}<Check /></span>)}</div> : <div className="domain-empty"><Globe2 /><span><strong>All domains are allowed</strong><small>Add domains in Settings to restrict access.</small></span></div>}</Card>
    <Card className="publish-card"><span><Sparkles /></span><div><h3>Ready to meet your visitors?</h3><p>Test the live preview, then publish the current version.</p></div><Button icon={RefreshCw} variant="secondary">Test endpoint</Button><Button icon={Zap}>Publish agent</Button></Card>
  </div>;
}

function CopyButton({ value, onCopied }: { value: string; onCopied?: () => void }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => { await navigator.clipboard.writeText(value); setCopied(true); onCopied?.(); window.setTimeout(() => setCopied(false), 1600); };
  return <button className="copy-button" onClick={() => void copy()} aria-label="Copy to clipboard">{copied ? <Check /> : <Copy />}{copied ? 'Copied' : 'Copy'}</button>;
}
