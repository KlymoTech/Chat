import {
  Activity, AlertTriangle, Building2, Database, MessagesSquare, Search, ShieldCheck,
  UsersRound,
} from 'lucide-react';
import { useEffect, useState, type FormEvent } from 'react';
import { Badge, Button, Card, PageLoader } from '@/components/ui';
import {
  platformAdminApi,
  type PlatformOverview,
  type PlatformTenantDetail,
  type PlatformTenantSummary,
} from '@/lib/platform-admin-api';

function formatPlan(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : '—';
}

function statusTone(status: string): 'success' | 'warning' | 'danger' | 'neutral' | 'brand' {
  if (['active', 'trial', 'healthy'].includes(status)) return 'success';
  if (['past_due', 'degraded'].includes(status)) return 'warning';
  if (['suspended', 'cancelled', 'critical'].includes(status)) return 'danger';
  return 'neutral';
}

export function PlatformAdminPage() {
  const [overview, setOverview] = useState<PlatformOverview | null>(null);
  const [tenants, setTenants] = useState<PlatformTenantSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState('');
  const [appliedQuery, setAppliedQuery] = useState('');
  const [selectedTenantId, setSelectedTenantId] = useState<string | null>(null);
  const [detail, setDetail] = useState<PlatformTenantDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    void Promise.all([
      platformAdminApi.overview(),
      platformAdminApi.tenants(appliedQuery),
    ]).then(([nextOverview, nextTenants]) => {
      if (!active) return;
      setOverview(nextOverview);
      setTenants(nextTenants.items);
      setTotal(nextTenants.total);
    }).catch((reason) => {
      if (!active) return;
      setError(reason instanceof Error ? reason.message : 'Platform control plane could not be loaded');
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [appliedQuery]);

  useEffect(() => {
    if (!selectedTenantId) return;
    let active = true;
    setDetailLoading(true);
    void platformAdminApi.tenant(selectedTenantId)
      .then((value) => { if (active) setDetail(value); })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : 'Tenant detail could not be loaded'); })
      .finally(() => { if (active) setDetailLoading(false); });
    return () => { active = false; };
  }, [selectedTenantId]);

  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    setSelectedTenantId(null);
    setDetail(null);
    setAppliedQuery(query.trim());
  };

  if (loading && !overview) return <PageLoader />;
  if (error && !overview) {
    return <div className="page"><Card className="workspace-panel"><div className="workspace-empty-row"><ShieldCheck /><span><strong>Platform administrator access required</strong><small>{error}</small></span></div></Card></div>;
  }

  const operations = overview?.operations;
  const operationalIssues = operations
    ? operations.failedIngestionJobs
      + operations.unpublishedOutboxEvents
      + operations.quarantinedEvents
      + operations.channelIssues
      + operations.crmConnectionIssues
      + operations.crmDeliveryIssues
      + operations.openCrmDeadLetters
      + operations.criticalAuditEvents24h
    : 0;

  const stats = [
    { label: 'Tenants', value: overview?.tenants ?? 0, note: `${overview?.workspaces ?? 0} workspaces`, icon: Building2 },
    { label: 'Active users', value: overview?.users ?? 0, note: `${overview?.agents ?? 0} agents`, icon: UsersRound },
    { label: 'Conversations', value: overview?.conversations ?? 0, note: `${overview?.leads ?? 0} leads`, icon: MessagesSquare },
    { label: 'Operational issues', value: operationalIssues, note: operations?.status ?? 'loading', icon: Activity },
  ];

  return <div className="page">
    <div className="page-heading page-heading--split">
      <div><span className="page-kicker">Northstar platform</span><h2>Control plane</h2><p>Read-only tenant, billing, operational health, CRM, channel and audit visibility.</p></div>
      <Badge tone={statusTone(operations?.status ?? 'unknown')}>{formatPlan(operations?.status ?? 'Loading')}</Badge>
    </div>

    <div className="stat-grid">
      {stats.map(({ label, value, note, icon: Icon }) => <Card className="stat-card" key={label}><div className="stat-card__icon stat-card__icon--blue"><Icon /></div><span>{label}</span><strong>{value.toLocaleString()}</strong><small>{note}</small></Card>)}
    </div>

    <Card className="workspace-panel">
      <div className="card-heading"><div><h3>Operations</h3><p>Durable worker, event, channel and CRM health from existing runtime tables.</p></div>{operationalIssues > 0 ? <Badge tone="warning"><AlertTriangle /> {operationalIssues} signals</Badge> : <Badge tone="success">Healthy</Badge>}</div>
      <div className="workspace-plan-grid">
        <Metric label="Failed ingestion jobs" value={operations?.failedIngestionJobs ?? 0} />
        <Metric label="Unpublished outbox events" value={operations?.unpublishedOutboxEvents ?? 0} note={operations?.oldestUnpublishedEventAt ? `Oldest ${formatDate(operations.oldestUnpublishedEventAt)}` : undefined} />
        <Metric label="Quarantined events" value={operations?.quarantinedEvents ?? 0} />
        <Metric label="Channel issues" value={operations?.channelIssues ?? 0} />
        <Metric label="CRM connection issues" value={operations?.crmConnectionIssues ?? 0} />
        <Metric label="CRM delivery issues" value={operations?.crmDeliveryIssues ?? 0} />
        <Metric label="Open CRM dead letters" value={operations?.openCrmDeadLetters ?? 0} />
        <Metric label="Critical audit signals · 24h" value={operations?.criticalAuditEvents24h ?? 0} />
      </div>
    </Card>

    <Card className="workspace-panel">
      <div className="card-heading"><div><h3>Plans & subscriptions</h3><p>Current tenant subscription lifecycle distribution.</p></div><Database /></div>
      <div className="workspace-plan-grid">
        <Metric label="Trial" value={overview?.subscriptions.trial ?? 0} />
        <Metric label="Active" value={overview?.subscriptions.active ?? 0} />
        <Metric label="Past due" value={overview?.subscriptions.pastDue ?? 0} />
        <Metric label="Suspended" value={overview?.subscriptions.suspended ?? 0} />
        <Metric label="Cancelled" value={overview?.subscriptions.cancelled ?? 0} />
      </div>
    </Card>

    <Card className="agents-snapshot">
      <div className="card-heading">
        <div><h3>Tenant administration</h3><p>{total.toLocaleString()} customer accounts · read-only support view</p></div>
        <form onSubmit={submitSearch} style={{ display: 'flex', gap: 8 }}><input aria-label="Search tenants" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search tenant or slug" /><Button type="submit" variant="secondary" icon={Search}>Search</Button></form>
      </div>
      <div className="agent-row-list">
        {tenants.map((tenant) => <button className="agent-row" type="button" key={tenant.id} onClick={() => setSelectedTenantId(tenant.id)} aria-pressed={tenant.id === selectedTenantId}>
          <span className="agent-avatar">{tenant.name.charAt(0).toUpperCase()}</span>
          <span className="agent-row__main"><strong>{tenant.name}</strong><small>{tenant.slug} · {tenant.workspaceCount} workspaces · {tenant.memberCount} members</small></span>
          <span className="agent-row__metric"><small>Agents</small><strong>{tenant.agentCount}</strong></span>
          <span className="agent-row__metric"><small>Conversations</small><strong>{tenant.conversationCount}</strong></span>
          <span className="agent-row__status"><Badge tone={statusTone(tenant.subscriptionStatus)}>{formatPlan(tenant.plan)} · {formatPlan(tenant.subscriptionStatus)}</Badge></span>
        </button>)}
        {!tenants.length ? <div className="mini-empty"><Building2 /><p>No tenants match this search.</p></div> : null}
      </div>
    </Card>

    {selectedTenantId ? <Card className="workspace-panel">
      {detailLoading || !detail ? <div className="workspace-empty-row"><Activity /><span><strong>Loading tenant support view…</strong></span></div> : <>
        <div className="card-heading"><div><h3>{detail.name}</h3><p>{detail.slug} · created {formatDate(detail.createdAt)}</p></div><Badge tone={statusTone(detail.subscriptionStatus)}>{formatPlan(detail.plan)} · {formatPlan(detail.subscriptionStatus)}</Badge></div>
        <div className="workspace-panel__body"><div className="workspace-empty-row"><Database /><span><strong>Billing</strong><small>Provider: {detail.provider ? formatPlan(detail.provider) : 'Not connected'}</small><small>Period end: {formatDate(detail.currentPeriodEnd)}</small><small>{detail.cancelAtPeriodEnd ? 'Cancellation scheduled' : 'No scheduled cancellation'}</small></span></div></div>
        <div className="card-heading"><div><h3>Workspaces</h3><p>Operational footprint for this tenant.</p></div></div>
        <div className="agent-row-list">{detail.workspaces.map((workspace) => <div className="agent-row" key={workspace.id}><span className="agent-avatar">{workspace.name.charAt(0).toUpperCase()}</span><span className="agent-row__main"><strong>{workspace.name}</strong><small>{workspace.slug} · {formatPlan(workspace.status)}</small></span><span className="agent-row__metric"><small>Members</small><strong>{workspace.memberCount}</strong></span><span className="agent-row__metric"><small>Agents</small><strong>{workspace.agentCount}</strong></span><span className="agent-row__metric"><small>Conversations</small><strong>{workspace.conversationCount}</strong></span></div>)}</div>
        <div className="card-heading"><div><h3>Recent audit/support context</h3><p>Metadata only; payload bodies remain in the tenant audit system.</p></div></div>
        <div className="agent-row-list">{detail.recentAudit.slice(0, 10).map((event) => <div className="agent-row" key={event.id}><span className="agent-avatar"><ShieldCheck /></span><span className="agent-row__main"><strong>{event.action}</strong><small>{event.category} · {event.entityType} · {event.entityId}</small></span><span className="agent-row__metric"><small>Outcome</small><strong>{formatPlan(event.outcome)}</strong></span><span className="agent-row__metric"><small>When</small><strong>{formatDate(event.createdAt)}</strong></span></div>)}</div>
      </>}
    </Card> : null}
  </div>;
}

function Metric({ label, value, note }: { label: string; value: number; note?: string }) {
  return <div><small>{label}</small><strong>{value.toLocaleString()}</strong>{note ? <small>{note}</small> : null}</div>;
}
