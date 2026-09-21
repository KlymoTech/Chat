import { Bot, CheckCircle2, Clock3, Inbox, MessageSquareText } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useAuth, useWorkspace } from '@/components/providers';
import { Badge, Card, EmptyState } from '@/components/ui';
import type { ExtendedBranding } from '@/features/workspace/settings/workspaceSettings.api';
import { api } from '@/lib/api';
import { formatCompact, formatPercent, relativeTime } from '@/lib/format';
import { useApi } from '@/lib/use-api';
import type { Agent, AnalyticsSummary, Conversation } from '@/types';
import './WorkspaceConfiguredDashboard.css';

export function WorkspaceConfiguredDashboard({ brand }: { brand: ExtendedBranding }) {
  const { session } = useAuth();
  const { activeWorkspace } = useWorkspace();
  const agents = useApi(() => api.agents.list());
  const conversations = useApi(() => api.conversations.list());
  const analytics = useApi(() => api.analytics.summary(7));
  const role = activeWorkspace?.role ?? '';
  const widgets = [...brand.dashboard.widgets]
    .filter((widget) => widget.visible && (widget.audience.length === 0 || widget.audience.includes(role)))
    .sort((left, right) => left.y - right.y || left.x - right.x);
  const open = conversations.data?.items.filter((item) => item.state !== 'resolved') ?? [];

  return <div className="page workspace-configured-dashboard">
    <div className="workspace-configured-dashboard__heading">
      <div><span className="page-kicker">{brand.identity.companyName || activeWorkspace?.name || 'Workspace'}</span><h2>Welcome back, {session?.user.name?.split(/\s+/)[0] || 'there'}</h2><p>{brand.dashboard.landingScreen === 'overview' ? 'Your published workspace dashboard.' : `Landing view: ${brand.dashboard.landingScreen}`}</p></div>
      <Badge tone="brand">Layout v{brand.dashboard.layoutVersion}</Badge>
    </div>
    <div className="workspace-configured-dashboard__grid">
      {widgets.map((widget) => <Card key={widget.id} className="workspace-configured-dashboard__widget" style={{ gridColumn: `${Math.max(1, widget.x + 1)} / span ${Math.max(1, widget.width)}`, gridRow: `${Math.max(1, widget.y + 1)} / span ${Math.max(1, widget.height)}` }}>
        <ConfiguredWidget type={widget.type} config={widget.config} agents={agents.data ?? []} open={open} analytics={analytics.data} loading={agents.loading || conversations.loading || analytics.loading} />
      </Card>)}
    </div>
    {widgets.length === 0 ? <EmptyState icon={Inbox} title="No dashboard widgets are published" description="A workspace administrator can add dashboard widgets in Workspace settings → White label → Dashboard." /> : null}
  </div>;
}

function ConfiguredWidget({ type, config, agents, open, analytics, loading }: { type: string; config: Record<string, unknown>; agents: Agent[]; open: Conversation[]; analytics: AnalyticsSummary | null | undefined; loading: boolean }) {
  const title = typeof config.title === 'string' && config.title.trim() ? config.title : defaultTitle(type);
  if (loading) return <div className="workspace-configured-dashboard__empty" role="status">Loading {title.toLowerCase()}…</div>;

  if (type === 'conversation-summary') return <div className="workspace-configured-dashboard__content"><h3>{title}</h3><div className="workspace-configured-dashboard__stats"><span><MessageSquareText /><strong>{analytics ? formatCompact(analytics.conversations) : '—'}</strong><small>Conversations</small></span><span><CheckCircle2 /><strong>{analytics ? formatPercent(analytics.resolutionRate) : '—'}</strong><small>Resolved by AI</small></span><span><Clock3 /><strong>{analytics ? `${analytics.avgResponseSeconds}s` : '—'}</strong><small>Avg. response</small></span></div><Link to="/conversations">Open conversations</Link></div>;
  if (type === 'agent-activity') return <div className="workspace-configured-dashboard__content"><h3>{title}</h3>{agents.length ? agents.slice(0, 5).map((agent) => <Link className="workspace-configured-dashboard__row" key={agent.id} to={`/agents/${agent.id}/instructions`}><Bot /><span><strong>{agent.name}</strong><small>{agent.status} · {formatCompact(agent.conversations)} conversations</small></span></Link>) : <p>No agents yet.</p>}</div>;
  if (type === 'usage') return <div className="workspace-configured-dashboard__content"><h3>{title}</h3><div className="workspace-configured-dashboard__stats"><span><Bot /><strong>{agents.filter((agent) => agent.status === 'active').length}</strong><small>Active agents</small></span><span><MessageSquareText /><strong>{analytics ? formatCompact(analytics.conversations) : '—'}</strong><small>7-day conversations</small></span></div></div>;
  if (type === 'channel-health') return <FeatureLink title={title} description="Review channel connections, delivery health, and connection status." href="/integrations" action="Open channels" />;
  if (type === 'crm-status') return <FeatureLink title={title} description="Review CRM connections and synchronization status." href="/integrations" action="Open CRM integrations" />;
  if (type === 'education-summary') return <FeatureLink title={title} description="Open education courses, batches, students, and learning workflows." href="/education" action="Open education" />;
  if (type === 'lead-summary') return <FeatureLink title={title} description="Review leads and sales activity for this workspace." href="/leads" action="Open leads" />;
  if (type === 'inbox-attention') return <div className="workspace-configured-dashboard__content"><h3>{title}</h3>{open.length ? open.slice(0, 5).map((item) => <Link className="workspace-configured-dashboard__row" key={item.id} to={`/conversations?selected=${item.id}`}><Inbox /><span><strong>{item.visitorName}</strong><small>{item.preview} · {relativeTime(item.updatedAt)}</small></span></Link>) : <p>You’re all caught up.</p>}</div>;
  return <FeatureLink title={title} description="This published widget uses configuration owned by the workspace dashboard layout." href="/" action="Open workspace" />;
}

function FeatureLink({ title, description, href, action }: { title: string; description: string; href: string; action: string }) {
  return <div className="workspace-configured-dashboard__content"><h3>{title}</h3><p>{description}</p><Link to={href}>{action}</Link></div>;
}

function defaultTitle(type: string) {
  return type.split('-').map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(' ');
}
