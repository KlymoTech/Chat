import { Bot, Check, ChevronDown, Download, Globe2, LayoutList, MessageCircle, MoreVertical, Plus, RefreshCw, Search, UsersRound, Webhook, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { LeadLayoutEditor } from '@/components/lead-layout-editor';
import { LeadDetailsEditor } from '@/components/lead-details-editor';
import { useAuth, useToast, useWorkspace } from '@/components/providers';
import { Button, EmptyState } from '@/components/ui';
import { api } from '@/lib/api';
import { defaultLayout, leadColumnValue, leadLayoutApi, type LeadLayout } from '@/lib/lead-layout-api';
import { leadCrmApi } from '@/lib/lead-crm-api';
import { leadStatuses } from '@/lib/lead-status';
import { useApi } from '@/lib/use-api';
import { usePollingApi } from '@/lib/use-polling-api';
import { canUseDashboardCapability } from '@/features/dashboard/dashboardPermissions';
import { AddLeadDialog } from '@/features/leads/LeadDialogs';
import { LeadDrawer } from '@/features/leads/LeadDrawer';
import { leadWorkspaceApi, type LeadWorkspace } from '@/features/leads/leadWorkspaceApi';
import { capturedAt, currentLeadWorkspace, displayName, initials, label, leadSource, sourceLabel } from '@/features/leads/presentation';
import type { Lead, PageResult } from '@/types';
import './LeadsPage.css';
import '@/features/leads/leads.css';

const PAGE_SIZE = 6;
const DEMO = import.meta.env.VITE_DEMO_MODE === 'true';
interface Filters { page: number; pageSize: number; search: string; status: string; agentId: string; channel: string }
async function loadLeads(filters: Filters): Promise<PageResult<Lead>> {
  if (!DEMO) return leadCrmApi.leads(filters);
  const page = await api.leads.list();
  const search = filters.search.trim().toLowerCase();
  const items = page.items.filter((lead) => (!search || `${lead.name || ''} ${lead.email || ''} ${lead.phone || ''}`.toLowerCase().includes(search))
    && (filters.status === 'all' || lead.status === filters.status) && (filters.agentId === 'all' || lead.agentId === filters.agentId)
    && (filters.channel === 'all' || leadSource(lead) === filters.channel));
  const start = (filters.page - 1) * filters.pageSize;
  return { items: items.slice(start, start + filters.pageSize), total: items.length, page: filters.page, pageSize: filters.pageSize };
}
/** Scope remount also clears open profiles, editing state and prior-tenant data. */
export function LeadsPage() {
  const { activeWorkspace } = useWorkspace(); const { session } = useAuth();
  const scope = { role: session?.user.role, permissions: activeWorkspace?.permissions };
  return <LeadsWorkspacePage key={activeWorkspace?.id ?? 'no-workspace'}
    canUpdate={canUseDashboardCapability(scope, 'leads.update')}
    canSync={canUseDashboardCapability(scope, 'crm.manage')}
    canConversation={canUseDashboardCapability(scope, 'conversations.view')} />;
}
export function LeadsWorkspacePage({ canUpdate, canSync, canConversation }: { canUpdate: boolean; canSync: boolean; canConversation: boolean }) {
  const [params, setParams] = useSearchParams(); const selectedId = params.get('lead');
  const [search, setSearch] = useState(''); const [status, setStatus] = useState('all');
  const [agentId, setAgentId] = useState('all'); const [channel, setChannel] = useState('all'); const [page, setPage] = useState(1);
  const [customizing, setCustomizing] = useState(false); const [editing, setEditing] = useState<Lead | null>(null); const [adding, setAdding] = useState(false);
  const [savedLayout, setSavedLayout] = useState<LeadLayout | null>(null); const [exporting, setExporting] = useState(false); const [updating, setUpdating] = useState('');
  const [workspaceOverride, setWorkspaceOverride] = useState<LeadWorkspace | null>(null);
  const layoutResult = useApi(() => leadLayoutApi.get()); const layout = savedLayout ?? layoutResult.data ?? defaultLayout;
  const leads = usePollingApi(() => loadLeads({ page, pageSize: PAGE_SIZE, search, status, agentId, channel }), [page, search, status, agentId, channel], 60000);
  const agents = useApi(() => api.agents.list()); const summary = useApi(() => leadWorkspaceApi.summary());
  const detail = usePollingApi(() => selectedId ? leadWorkspaceApi.detail(selectedId) : Promise.resolve(null), [selectedId], 60000);
  const selected = currentLeadWorkspace(selectedId, detail.data, workspaceOverride);
  const records = leads.data?.items ?? []; const total = leads.data?.total ?? 0; const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const { pushToast } = useToast(); const agentNames = useMemo(() => new Map((agents.data ?? []).map((agent) => [agent.id, agent.name])), [agents.data]);
  const customColumns = layout.version > 0;
  function select(id: string | null) { setWorkspaceOverride(null); const next = new URLSearchParams(params); if (id) next.set('lead', id); else next.delete('lead'); setParams(next, { replace: true }); }
  function savedWorkspace(value: LeadWorkspace) { setWorkspaceOverride(value); detail.reload(); }
  function refresh() { setWorkspaceOverride(null); leads.reload(); summary.reload(); detail.reload(); }
  function filter(setter: (value: string) => void, value: string) { setPage(1); setter(value); }
  async function updateStatus(lead: Lead, next: string) {
    setUpdating(lead.id); try { const saved = await api.leads.updateStatus(lead.id, next); pushToast(saved.status === 'qualified' ? `${displayName(lead)} marked Qualified. Resolved leads sync automatically using your CRM settings.` : `${displayName(lead)} marked ${saved.status}`); refresh(); }
    catch (e) { pushToast(e instanceof Error ? e.message : 'Could not update lead', 'error'); } finally { setUpdating(''); }
  }
  async function exportLeads(format: 'csv' | 'xlsx') { setExporting(true); try { await leadLayoutApi.export(format, search, status, { agentId, channel }); pushToast('All matching leads exported'); } catch (e) { pushToast(e instanceof Error ? e.message : 'Export failed', 'error'); } finally { setExporting(false); } }
  const statusControl = (lead: Lead) => <label className={`ld-status-control ld-stage--${lead.status}`}><span className="sr-only">Status for {displayName(lead)}</span><select value={lead.status} disabled={!canUpdate || updating === lead.id} onChange={(e) => void updateStatus(lead, e.target.value)}>{[...new Set([lead.status, ...leadStatuses])].map((value) => <option key={value} value={value}>{label(value)}</option>)}</select></label>;
  const metricItems = [ ['Total captured leads', summary.data?.total, 'Workspace total'], ['New leads', summary.data?.new, 'Requires review'], ['Qualified', summary.data?.qualified, 'Current stage'], ['Converted', summary.data?.converted, summary.data ? `${summary.data.total ? ((summary.data.converted / summary.data.total) * 100).toFixed(1) : '0.0'}% of total` : 'Workspace total'] ] as const;
  return <div className="page leads-page ld-page">
    <header className="ld-heading"><div className="ld-heading__top"><span className="ld-eyebrow">Live Pipeline</span><div><Button icon={Download} disabled={exporting || !total || Boolean(layoutResult.error)} onClick={() => void exportLeads('csv')}>{exporting ? 'Exporting…' : 'Export CSV'}</Button><Button icon={Plus} disabled={!canUpdate || agents.loading || Boolean(agents.error)} onClick={() => setAdding(true)}>Add Lead</Button></div></div><h2>Leads</h2><p>Track, score, and push inbound prospects captured autonomously across your conversational AI fleet.</p></header>
    <section className="ld-metrics" aria-label="Workspace lead totals">{metricItems.map(([name, value, hint], index) => <article key={name} className="ld-metric"><h3>{name}</h3><strong>{summary.loading || summary.error ? '—' : value}</strong><small className={`ld-metric__hint ld-metric__hint--${index}`}>{hint}</small></article>)}</section>
    {summary.error && <p className="ld-inline-error" role="alert">Lead totals are unavailable. <button onClick={summary.reload}>Retry totals</button></p>}
    <section className="ld-list" aria-label="Captured leads"><div className="ld-list-heading"><h3>All Captured Leads</h3><p>Review conversation context, consent logs, and lead routing.</p></div>
      <div className="ld-toolbar"><div className="ld-search"><Search /><input aria-label="Search leads" placeholder="Search name, email, or phone" value={search} onChange={(e) => filter(setSearch, e.target.value)} />{search && <button type="button" aria-label="Clear lead search" onClick={() => filter(setSearch, '')}><X /></button>}</div>
        <div className="ld-filters"><label className="ld-filter ld-filter--primary"><span>Status:</span><select aria-label="Filter leads by status" value={status} onChange={(e) => filter(setStatus, e.target.value)}><option value="all">All</option>{leadStatuses.map((value) => <option key={value} value={value}>{label(value)}</option>)}</select><ChevronDown /></label>
        <label className="ld-filter"><span>Agent:</span><select aria-label="Filter leads by agent" value={agentId} onChange={(e) => filter(setAgentId, e.target.value)} disabled={agents.loading || Boolean(agents.error)}><option value="all">All</option>{agents.data?.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select><ChevronDown /></label>
        <label className="ld-filter"><span>Source:</span><select aria-label="Filter leads by source" value={channel} onChange={(e) => filter(setChannel, e.target.value)}><option value="all">All</option>{['widget', 'whatsapp', 'telegram', 'api'].map((value) => <option key={value} value={value}>{sourceLabel(value)}</option>)}</select><ChevronDown /></label></div>
        <button type="button" className="ld-tool-button" aria-label="Customize columns" title="Customize columns" disabled={layoutResult.loading || Boolean(layoutResult.error) || !canUpdate} onClick={() => setCustomizing(true)}><LayoutList /></button><button type="button" className="ld-tool-button" aria-label="Refresh leads" title="Refresh leads" onClick={refresh} disabled={leads.loading}><RefreshCw /></button>
      </div>
      {layoutResult.error && <p role="alert" className="ld-inline-error">Could not load your saved layout. <button onClick={layoutResult.reload}>Retry layout</button></p>}{agents.error && <p role="alert" className="ld-inline-error">Agent names could not be loaded. <button onClick={agents.reload}>Retry agents</button></p>}
      {leads.loading && !leads.data ? <div className="ld-list-loading" role="status">Loading captured leads…</div> : leads.error ? <EmptyState icon={UsersRound} title="Leads are unavailable" description={leads.error} action={<Button onClick={leads.reload}>Try again</Button>} /> : records.length ? <div className="ld-table-scroll" tabIndex={0} role="region" aria-label="Lead records"><table className="ld-table"><thead><tr>{customColumns ? layout.columns.filter((column) => column.visible).map((column) => <th scope="col" key={column.id}>{column.label}</th>) : ['Lead', 'Contact', 'Source', 'Agent', 'Status', 'Consent', 'Captured'].map((column) => <th scope="col" key={column}>{column}</th>)}<th scope="col">Actions</th></tr></thead><tbody>{records.map((lead) => {
        const source = leadSource(lead); const SourceIcon = source === 'widget' || source === 'website' ? Globe2 : source === 'api' ? Webhook : MessageCircle;
        return <tr key={lead.id} className={selectedId === lead.id ? 'is-selected' : ''}>{customColumns ? layout.columns.filter((column) => column.visible).map((column) => <td key={column.id}>{column.source === 'status' ? statusControl(lead) : column.source === 'name' ? <button type="button" className="ld-name" aria-label={displayName(lead)} onClick={() => select(lead.id)}><span className="ld-avatar">{initials(displayName(lead))}</span><strong>{displayName(lead)}</strong></button> : leadColumnValue(lead, column, agentNames.get(lead.agentId)) || 'Not provided'}</td>) : <>
          <td><button type="button" className="ld-name" aria-label={displayName(lead)} onClick={() => select(lead.id)}><span className="ld-avatar">{initials(displayName(lead))}</span><strong>{displayName(lead)}</strong></button></td><td className="ld-contact"><strong>{lead.email || 'Email not provided'}</strong><small>{lead.phone || 'Phone not provided'}</small></td><td><span className={`ld-source ld-source--${source}`}><SourceIcon />{sourceLabel(source)}</span></td><td><span className="ld-agent"><Bot />{agentNames.get(lead.agentId) || 'Not available'}</span></td><td>{statusControl(lead)}</td><td><span className={lead.consent ? 'ld-consent-yes' : 'ld-consent-no'}>{lead.consent ? <Check /> : '–'}{lead.consent ? 'Yes' : 'No'}</span></td><td className="ld-captured"><time dateTime={lead.createdAt} title={new Date(lead.createdAt).toLocaleString()}>{capturedAt(lead.createdAt)}</time></td></>}
          <td><details className="ld-row-menu"><summary aria-label={`Actions for ${displayName(lead)}`}><MoreVertical /></summary><div><button type="button" onClick={() => select(lead.id)}>View details</button><button type="button" onClick={() => select(lead.id)}>View sync</button><button type="button" disabled={!canUpdate || Boolean(layoutResult.error)} onClick={() => setEditing(lead)}>Edit details</button></div></details></td></tr>;
      })}</tbody></table></div> : <EmptyState icon={UsersRound} title="No leads found" description={search || status !== 'all' || agentId !== 'all' || channel !== 'all' ? 'Try another search or filter.' : 'New contacts captured by your channels will appear here.'} action={canUpdate ? <Button icon={Plus} onClick={() => setAdding(true)}>Add Lead</Button> : undefined} />}
      <footer className="ld-pagination"><small>{leads.loading ? 'Loading…' : `Showing ${total ? (page - 1) * PAGE_SIZE + 1 : 0} – ${Math.min(page * PAGE_SIZE, total)} of ${total} leads`}</small><div><Button variant="secondary" size="sm" disabled={page <= 1 || leads.loading} onClick={() => setPage((value) => value - 1)}>Previous</Button>{Array.from({ length: Math.min(5, totalPages) }, (_, index) => Math.max(1, Math.min(page - 2, totalPages - 4)) + index).map((number) => <button type="button" key={number} aria-current={page === number ? 'page' : undefined} aria-label={`Page ${number}`} disabled={leads.loading} onClick={() => setPage(number)}>{number}</button>)}<Button variant="secondary" size="sm" disabled={page >= totalPages || leads.loading} onClick={() => setPage((value) => value + 1)}>Next</Button></div></footer>
      <details className="ld-export-options"><summary>Additional export options</summary><Button variant="secondary" icon={Download} disabled={exporting || !total || Boolean(layoutResult.error)} onClick={() => void exportLeads('xlsx')}>Export Excel</Button><span>Saved custom columns and all active filters are respected.</span></details>
    </section>
    {selectedId && (!selected || selected.lead.id !== selectedId) && <aside className="ld-drawer ld-drawer--loading" role="dialog" aria-label="Lead details"><button type="button" className="icon-button" aria-label="Close lead details" onClick={() => select(null)}><X /></button>{detail.error ? <div role="alert"><h3>Lead is unavailable</h3><p>{detail.error}</p><Button onClick={detail.reload}>Try again</Button></div> : <p role="status">Loading lead details…</p>}</aside>}
    {selectedId && selected?.lead.id === selectedId && <LeadDrawer key={selectedId} workspace={selected} agent={agents.data?.find((agent) => agent.id === selected.lead.agentId)} canUpdate={canUpdate} canSync={canSync} canConversation={canConversation} onClose={() => select(null)} onSaved={savedWorkspace} onLeadSaved={(lead) => { setWorkspaceOverride({ ...selected, lead }); detail.reload(); leads.reload(); summary.reload(); pushToast('Lead status updated'); }} onEdit={() => setEditing(selected.lead)} />}
    {customizing && <LeadLayoutEditor initial={layout} records={records} agentNames={agentNames} onClose={() => setCustomizing(false)} onSaved={setSavedLayout} />}
    {editing && <LeadDetailsEditor lead={editing} layout={layout} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); refresh(); pushToast('Lead details saved'); }} />}
    {adding && <AddLeadDialog agents={agents.data ?? []} onClose={() => setAdding(false)} onSaved={(lead) => { setAdding(false); refresh(); select(lead.id); pushToast('Lead added'); }} />}
  </div>;
}
