import { ArrowLeft, ArrowRight, Bot, CheckCircle2, Clock3, Database, Inbox, MessageSquareText, Plug, Plus } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useAuth, useWorkspace } from '@/components/providers';
import { Badge, Button, EmptyState } from '@/components/ui';
import { DashboardTrend } from '@/components/academy-dashboard';
import { api } from '@/lib/api';
import { loadAttentionConversations } from '@/lib/attention-api';
import { formatCompact, formatPercent, relativeTime } from '@/lib/format';
import { canUseDashboardCapability } from './dashboardPermissions';
import { useApi, type AsyncState } from '@/lib/use-api';
import type { Agent } from '@/types';

/** Figma 59:12884. Sample statistics are deliberately replaced with API data. */
export function SaasBotOverview() {
  const { session } = useAuth();
  const { activeWorkspace } = useWorkspace();
  const scope = { role: session?.user.role, permissions: activeWorkspace?.permissions };
  const canAgents = canUseDashboardCapability(scope, 'agents.view');
  const canCreate = canAgents && canUseDashboardCapability(scope, 'agents.create');
  const canKnowledge = canUseDashboardCapability(scope, 'knowledge.view');
  const canAnalytics = canUseDashboardCapability(scope, 'analytics.view');
  const canInbox = canUseDashboardCapability(scope, 'conversations.view');
  const canIntegrations = canUseDashboardCapability(scope, 'integrations.view');
  const [period, setPeriod] = useState<7 | 30>(7);
  const [filter, setFilter] = useState('all');
  const [metric, setMetric] = useState<'conversations' | 'resolved'>('conversations');
  const [selected, setSelected] = useState(0);
  const [today] = useState(() => new Date());
  const agents = useApi(() => canAgents ? api.agents.list() : Promise.resolve([]), [canAgents]);
  const analytics = useApi(() => canAnalytics ? api.analytics.summary(period) : Promise.resolve(null), [canAnalytics, period]);
  const conversations = useApi(() => canInbox ? loadAttentionConversations() : Promise.resolve(null), [canInbox]);
  const records = ready(agents) ?? [];
  // A workspace change or deleted agent can invalidate the saved carousel index.
  // `records` contains only successfully loaded current-scope data.
  const featured = records.length > 0 ? records[selected % records.length] : undefined;
  const summary = ready(analytics);
  const shown = records.filter((agent) => filter === 'all' || (filter === 'education' ? agent.purpose === 'education' : agent.status === filter));
  const open = ready(conversations)?.items.filter((item) => item.state !== 'resolved') ?? [];
  const count = !canAgents || !ready(agents) ? '—' : records.filter((agent) => agent.status === 'active').length;
  const unavailable = canAnalytics ? 'Unavailable until statistics load' : 'Analytics access required';

  return <div className="page sb-overview">
    <section className="sb-hero" aria-labelledby="sb-welcome">
      <div className="sb-hero__copy">
        <div className="sb-hero__eyebrow"><time dateTime={today.toISOString().slice(0, 10)}>{today.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}</time><span>{activeWorkspace?.name ?? 'Your workspace'}</span></div>
        <h2 id="sb-welcome">Hello {session?.user.name?.trim().split(/\s+/)[0] || 'there'}!</h2>
        <p>Your AI workspace, at a glance.<br />Manage your agents, conversations, and knowledge in one place.</p>
        <div className="sb-hero__actions">
          {featured ? <Link className="sb-hero__agent" to={`/agents/${featured.id}/instructions`}><Bot aria-hidden="true" />{featured.name}<Badge tone={featured.status === 'active' ? 'success' : 'neutral'}>{featured.status}</Badge></Link> : null}
          {canCreate ? <Link className="button sb-hero__create" to="/agents?create=1"><Plus aria-hidden="true" />Create agent</Link> : null}
        </div>
      </div>
      {/* The original Figma illustration is pending export; do not substitute a different asset. */}
    </section>

    <section className="sb-metrics" aria-label="Workspace summary">
      <Metric icon={<Bot />} label="Active agents" value={count} detail={canAgents ? 'Current workspace' : 'Agent access required'} />
      <Metric icon={<MessageSquareText />} label="Conversations" value={summary ? formatCompact(summary.conversations) : '—'} detail={summary ? `Last ${period} days` : unavailable} />
      <Metric icon={<Clock3 />} label="Average response" value={summary ? `${summary.avgResponseSeconds}s` : '—'} detail={summary ? `Last ${period} days` : unavailable} />
      <Metric icon={<CheckCircle2 />} label="Resolved conversations" value={summary ? formatPercent(summary.resolutionRate) : '—'} detail={summary ? `Last ${period} days` : unavailable} />
    </section>

    <div className="sb-overview__columns">
      <div className="sb-overview__primary">
        {canAgents ? <>
          {featured ? <div className="sb-featured">
            <Link className="sb-featured__record" aria-label={`Continue with ${featured.name}`} to={`/agents/${featured.id}/instructions`}>
              <span className="sb-agent-icon"><Bot aria-hidden="true" /></span><span><strong>{featured.name}</strong><small>{featured.appearance.deploymentChannel === 'whatsapp' ? featured.whatsappNumber || 'WhatsApp · number needed' : 'Your selected agent'}</small></span>
              <Badge tone={featured.status === 'active' ? 'success' : 'neutral'}>{featured.status}</Badge>
            </Link>
            <div className="sb-carousel"><button type="button" disabled={records.length < 2} aria-label="Previous agent" onClick={() => setSelected((value) => (value + records.length - 1) % records.length)}><ArrowLeft /></button><button type="button" disabled={records.length < 2} aria-label="Next agent" onClick={() => setSelected((value) => (value + 1) % records.length)}><ArrowRight /></button></div>
          </div> : null}
          <section className="sb-agents" aria-labelledby="sb-agents-title">
            <div className="sb-section-heading"><h3 id="sb-agents-title">Your agents</h3><Link to="/agents">Manage agents <ArrowRight aria-hidden="true" /></Link></div>
            <div className="sb-tabs" role="group" aria-label="Filter agents">{[['all', 'All agents'], ['active', 'Active'], ['draft', 'Draft'], ['education', 'Education']].map(([id, label]) => <button key={id} type="button" aria-pressed={filter === id} onClick={() => setFilter(id!)}>{label}</button>)}</div>
            {agents.error ? <Failure title="Agents are unavailable" state={agents} /> : agents.loading ? <Loading>Loading your agents…</Loading> : shown.length ? <div className="sb-agent-list">{shown.map((agent) => <AgentRow key={agent.id} agent={agent} />)}</div> : <EmptyState icon={Bot} title={records.length ? 'No matching agents' : canCreate ? 'Create your first agent' : 'No agents yet'} description={canCreate ? 'Build an assistant for your customers or students.' : 'An authorized workspace member can create an agent.'} action={canCreate ? <Link className="button button--primary" to="/agents?create=1">Create agent</Link> : undefined} />}
          </section>
        </> : <AccessNotice>Agent access is required to view your agents.</AccessNotice>}

        <section className="sb-panel sb-statistics" aria-labelledby="sb-statistics-title">
          <h3 id="sb-statistics-title">Your statistics</h3>
          {canAnalytics ? <>
            <div className="sb-statistics__controls"><div className="sb-tabs" role="group" aria-label="Chart metric"><button type="button" aria-pressed={metric === 'conversations'} onClick={() => setMetric('conversations')}>Conversations</button><button type="button" aria-pressed={metric === 'resolved'} onClick={() => setMetric('resolved')}>Resolved</button></div><select aria-label="Chart period" value={period} onChange={(event) => setPeriod(Number(event.target.value) as 7 | 30)}><option value="7">Weekly</option><option value="30">Monthly</option></select></div>
            {analytics.error ? <Failure title="Statistics are unavailable" state={analytics} /> : analytics.loading ? <Loading>Loading statistics…</Loading> : <DashboardTrend label={metric === 'conversations' ? 'Conversation volume trend' : 'Resolved conversations trend'} data={(summary?.chart ?? []).map((item) => ({ label: item.label, value: item[metric] }))} />}
          </> : <AccessNotice>Analytics access is required to view statistics.</AccessNotice>}
        </section>
      </div>

      <aside className="sb-overview__secondary" aria-label="Workspace activity">
        {canAgents && canKnowledge ? featured ? <KnowledgeHealth key={featured.id} agent={featured} /> : <section className="sb-panel"><h3>Knowledge health</h3><p>{agents.loading ? 'Loading your agents…' : agents.error ? 'Available when your agents can be loaded.' : 'Create an agent to connect trusted knowledge.'}</p></section> : null}
        {canIntegrations ? <ConnectedChannels /> : <AccessNotice>Integration access is required to view channel connections.</AccessNotice>}
        {canInbox ? <section className="sb-attention" aria-labelledby="sb-attention-title"><div className="sb-section-heading"><h3 id="sb-attention-title">Needs attention</h3><Link to="/conversations">View inbox <ArrowRight aria-hidden="true" /></Link></div>
          {conversations.error ? <Failure title="Inbox is unavailable" state={conversations} /> : conversations.loading ? <Loading>Loading conversations…</Loading> : open.length ? <div className="sb-attention__list">{open.slice(0, 3).map((item) => <Link className="sb-inbox-row" key={item.id} to={`/conversations?selected=${encodeURIComponent(item.id)}`}><span className="mini-avatar" aria-hidden="true">{item.visitorName.charAt(0)}</span><span className="sb-inbox-row__copy"><strong>{item.visitorName}</strong><small>{item.preview}</small></span><time dateTime={item.updatedAt}>{relativeTime(item.updatedAt)}</time></Link>)}</div> : <div className="sb-empty"><Inbox aria-hidden="true" /><p>You’re all caught up.</p></div>}
        </section> : null}
        <section className="sb-learning-tip"><h3>Learn even more!</h3><p>Give your agents more knowledge.<br />Make every answer more useful.</p><Link className="button" to="/help">Explore the Help Center <ArrowRight aria-hidden="true" /></Link></section>
      </aside>
    </div>
  </div>;
}

function ready<T>(state: AsyncState<T>): T | null {
  // Do not display a previous period or failed request as current live data.
  return !state.loading && !state.error ? state.data : null;
}
function Loading({ children }: { children: ReactNode }) { return <p className="sb-empty" role="status">{children}</p>; }
function AccessNotice({ children }: { children: ReactNode }) { return <p className="sb-panel sb-access-notice">{children}</p>; }
function Failure({ title, state }: { title: string; state: Pick<AsyncState<unknown>, 'error' | 'reload'> }) {
  return <div className="sb-error" role="alert"><strong>{title}</strong><p>{state.error}</p><Button variant="secondary" size="sm" onClick={state.reload}>Try again</Button></div>;
}
function Metric({ icon, label, value, detail }: { icon: ReactNode; label: string; value: ReactNode; detail: string }) {
  return <article className="sb-metric" aria-label={label}><div className="sb-metric__label"><span aria-hidden="true">{icon}</span><h3>{label}</h3></div><strong className="sb-metric__value">{value}</strong><small>{detail}</small></article>;
}
function AgentRow({ agent }: { agent: Agent }) {
  return <article className="sb-agent-row"><span className="sb-agent-icon" aria-hidden="true"><Bot /></span><div className="sb-agent-row__name"><h4>{agent.name}</h4><p>{agent.description || `${agent.purpose === 'education' ? 'Education' : 'AI'} assistant`}</p></div><span className="sb-agent-row__metric" title="Conversations"><MessageSquareText aria-hidden="true" />{formatCompact(agent.conversations)}</span><span className="sb-agent-row__metric" title="Resolution rate"><CheckCircle2 aria-hidden="true" />{formatPercent(agent.resolutionRate)}</span><Link className="button button--primary button--sm" to={`/agents/${agent.id}/instructions`} aria-label={`Open ${agent.name}`}>Open <ArrowRight aria-hidden="true" /></Link></article>;
}
function KnowledgeHealth({ agent }: { agent: Agent }) {
  const sources = useApi(() => api.knowledge.list(agent.id), [agent.id]);
  const items = ready(sources);
  const readyCount = items?.filter((item) => item.status === 'ready').length ?? 0;
  const lastUpdated = items?.map((item) => item.updatedAt).filter((value) => Number.isFinite(Date.parse(value))).sort((a, b) => Date.parse(b) - Date.parse(a))[0];
  return <section className="sb-panel sb-knowledge" aria-label={`Knowledge health for ${agent.name}`}><div className="sb-section-heading"><h3>Knowledge health</h3><Database aria-hidden="true" /></div><p className="sb-panel__scope">{agent.name}</p>
    {sources.error ? <Failure title="Knowledge is unavailable" state={sources} /> : sources.loading ? <Loading>Loading knowledge…</Loading> : <>
      <div className="sb-knowledge__count"><strong>{readyCount} <span>/ {items?.length ?? 0}</span></strong><span>Sources ready</span></div>
      <progress aria-label={`Ready knowledge sources for ${agent.name}`} value={readyCount} max={Math.max(items?.length ?? 0, 1)} />
      <p>{lastUpdated ? <>Last source update <time dateTime={lastUpdated}>{relativeTime(lastUpdated)}</time></> : 'No knowledge sources yet.'}</p>
    </>}
    <Link className="button button--primary" to={`/agents/${agent.id}/knowledge`}>Manage knowledge <ArrowRight aria-hidden="true" /></Link>
  </section>;
}
function ConnectedChannels() {
  const integrations = useApi(() => api.integrations.list());
  const channels = ready(integrations)?.filter((item) => item.category === 'channel' && !item.comingSoon) ?? [];
  return <section className="sb-panel sb-channels"><div className="sb-section-heading"><h3>Connected channels</h3><Plug aria-hidden="true" /></div>
    {integrations.error ? <Failure title="Connections are unavailable" state={integrations} /> : integrations.loading ? <Loading>Loading connections…</Loading> : channels.length ? <ul>{channels.map((channel) => <li key={channel.id}><span>{channel.name}</span><span className={channel.connected ? 'sb-channel-status is-connected' : 'sb-channel-status'}>{channel.connected ? 'Connected' : 'Not connected'}</span></li>)}</ul> : <p>No channel connections are available.</p>}
    <Link className="sb-text-link" to="/integrations">Manage integrations <ArrowRight aria-hidden="true" /></Link>
  </section>;
}
