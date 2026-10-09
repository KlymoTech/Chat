import { Bot, CalendarDays, CheckCircle2, Copy, Expand, Globe2, Mail, MessageSquare, Minimize2, Phone, UserPlus, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui';
import { useToast } from '@/components/providers';
import type { Lead, Agent } from '@/types';
import { AssignLeadDialog, FollowUpDialog, FollowUpList, LeadStageDialog } from './LeadDialogs';
import { LeadCRMPanel } from './LeadCRMPanel';
import type { LeadWorkspace } from './leadWorkspaceApi';
import { capturedAt, displayName, initials, label, leadSource, sourceLabel, stringField } from './presentation';

export function LeadDrawer({ workspace, agent, canUpdate, canSync, canConversation, onClose, onSaved, onLeadSaved, onEdit }: {
  workspace: LeadWorkspace; agent?: Agent; canUpdate: boolean; canSync: boolean; canConversation: boolean;
  onClose: () => void; onSaved: (value: LeadWorkspace) => void; onLeadSaved: (lead: Lead) => void; onEdit: () => void;
}) {
  const { lead } = workspace; const [expanded, setExpanded] = useState(false);
  const [dialog, setDialog] = useState<'stage' | 'assign' | 'followup' | null>(null);
  const ref = useRef<HTMLElement>(null); const closeRef = useRef(onClose); const { pushToast } = useToast();
  useEffect(() => { closeRef.current = onClose; }, [onClose]);
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    ref.current?.querySelector<HTMLButtonElement>('[aria-label="Close lead details"]')?.focus();
    const escape = (e: KeyboardEvent) => { if (e.key === 'Escape' && !document.querySelector('.modal-backdrop')) closeRef.current(); };
    window.addEventListener('keydown', escape);
    return () => { window.removeEventListener('keydown', escape); if (previous?.isConnected) previous.focus(); };
  }, []);
  async function copy(value: string) { try { await navigator.clipboard.writeText(value); pushToast('Copied to clipboard'); } catch { pushToast('Clipboard access is unavailable. Select and copy the contact value.', 'error'); } }
  const company = stringField(lead, 'company'); const jobTitle = stringField(lead, 'jobTitle');
  const location = stringField(lead, 'location'); const timezone = stringField(lead, 'timezone');
  return <aside ref={ref} className={`ld-drawer${expanded ? ' ld-drawer--expanded' : ''}`} role="dialog" aria-modal="false" aria-label={`Lead details: ${displayName(lead)}`}>
    <header className="ld-drawer__header"><span className="ld-avatar ld-avatar--large">{initials(displayName(lead))}</span><div><h3>{displayName(lead)}</h3><p>{[company, jobTitle].filter(Boolean).join(' · ') || lead.email || 'Contact profile'}</p></div><button type="button" className="icon-button" aria-label={expanded ? 'Reduce lead details' : 'Expand lead details'} onClick={() => setExpanded(!expanded)}>{expanded ? <Minimize2 /> : <Expand />}</button><button type="button" className="icon-button" aria-label="Close lead details" onClick={onClose}><X /></button></header>
    <div className="ld-drawer__body"><div className="ld-current-stage"><span>Current stage:</span><span className={`ld-stage ld-stage--${lead.status}`}>{label(lead.status)}</span><button type="button" disabled={!canUpdate} onClick={() => setDialog('stage')}>Change⌄</button></div>
      <section><h4 className="ld-green-label">Contact details</h4><div className="ld-contact-block">{lead.email ? <div><Mail /><a href={`mailto:${encodeURIComponent(lead.email)}`}>{lead.email}</a><button type="button" className="icon-button" aria-label="Copy email" onClick={() => void copy(lead.email!)}><Copy /></button></div> : <p>Email not provided</p>}{lead.phone ? <div><Phone /><a href={`tel:${lead.phone.replace(/[^\d+]/g, '')}`}>{lead.phone}</a><button type="button" className="icon-button" aria-label="Copy phone" onClick={() => void copy(lead.phone!)}><Copy /></button></div> : <p>Phone not provided</p>}{location || timezone ? <div><Globe2 /><span>{[location, timezone].filter(Boolean).join(' · ')}</span></div> : null}</div>{canUpdate && <button type="button" className="ld-text-button" onClick={onEdit}>Edit details</button>}</section>
      <section><h4 className="ld-green-label">Lead origin &amp; telemetry</h4><dl className="ld-telemetry"><div><dt>Source channel</dt><dd><Globe2 />{sourceLabel(leadSource(lead))}</dd></div><div><dt>Assigned agent</dt><dd><Bot />{agent?.name || 'Not available'}</dd></div><div><dt>Captured at</dt><dd>{capturedAt(lead.createdAt)}</dd></div><div><dt>Consent status</dt><dd className={lead.consent ? 'ld-consent-yes' : 'ld-consent-no'}><CheckCircle2 />{lead.consent ? 'Explicit opt-in' : 'Not recorded'}</dd></div></dl></section>
      <LeadCRMPanel key={lead.id} lead={lead} canSync={canSync} />
      {workspace.assignment && <section><h4 className="ld-green-label">Assigned owner</h4><div className="ld-owner"><span className="ld-avatar">{initials(workspace.assignment.name)}</span><span><strong>{workspace.assignment.name}</strong><small>{label(workspace.assignment.kind)}</small></span></div>{workspace.assignment.note && <p className="ld-muted">{workspace.assignment.note}</p>}</section>}
      <details className="ld-followups" open={workspace.followUps.length > 0}><summary>Follow-ups <span>{workspace.followUps.length}</span></summary><FollowUpList workspace={workspace} canUpdate={canUpdate} onSaved={onSaved} /></details>
    </div>
    <footer className="ld-drawer__footer"><Button icon={UserPlus} disabled={!canUpdate} className="ld-full" onClick={() => setDialog('assign')}>Assign</Button><div>{lead.conversationId && canConversation ? <Link className="button button--secondary" to={`/conversations?selected=${encodeURIComponent(lead.conversationId)}`}><MessageSquare />Transcript</Link> : <Button variant="secondary" disabled title={lead.conversationId ? 'Conversation access is required' : 'No conversation is linked to this lead'} icon={MessageSquare}>Transcript</Button>}<Button variant="secondary" icon={CalendarDays} disabled={!canUpdate} onClick={() => setDialog('followup')}>Follow-up</Button></div></footer>
    {dialog === 'stage' && <LeadStageDialog lead={lead} onClose={() => setDialog(null)} onSaved={(saved) => { setDialog(null); onLeadSaved(saved); }} />}
    {dialog === 'assign' && <AssignLeadDialog workspace={workspace} onClose={() => setDialog(null)} onSaved={(saved) => { setDialog(null); onSaved(saved); pushToast('Lead owner updated'); }} />}
    {dialog === 'followup' && <FollowUpDialog workspace={workspace} onClose={() => setDialog(null)} onSaved={(saved) => { setDialog(null); onSaved(saved); pushToast('Follow-up saved. Download its calendar reminder from the lead details.'); }} />}
  </aside>;
}
