import { CreditCard, Sparkles } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { useToast } from '@/components/providers';
import { Badge, Button, Card } from '@/components/ui';
import {
  billingApi,
  type SubscriptionStatus,
  type TenantEntitlements,
  type TenantSubscription,
} from '@/lib/billing-api';
import type { WorkspaceSettings } from '@/lib/workspace-api';

const statusLabels: Record<SubscriptionStatus, string> = {
  trial: 'Trial',
  active: 'Active',
  past_due: 'Past due',
  suspended: 'Suspended',
  cancelled: 'Cancelled',
};

export function SubscriptionBillingPanel({ workspace }: { workspace: WorkspaceSettings }) {
  const { pushToast } = useToast();
  const [subscription, setSubscription] = useState<TenantSubscription | null>(null);
  const [entitlements, setEntitlements] = useState<TenantEntitlements | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    setError('');
    void Promise.all([
      billingApi.getSubscription(workspace.plan),
      billingApi.getEntitlements(workspace.plan),
    ])
      .then(([nextSubscription, nextEntitlements]) => {
        if (!active) return;
        setSubscription(nextSubscription);
        setEntitlements(nextEntitlements);
      })
      .catch((reason) => {
        if (!active) return;
        const message = reason instanceof Error ? reason.message : 'Billing information could not be loaded';
        setError(message);
        pushToast(message, 'error');
      });
    return () => { active = false; };
  }, [pushToast, workspace.id, workspace.plan]);

  const plan = subscription?.plan ?? entitlements?.plan ?? workspace.plan;
  const statusValue = subscription?.status ?? entitlements?.subscriptionStatus;
  const status = statusValue ? statusLabels[statusValue] : 'Loading';
  const period = subscription?.currentPeriodEnd
    ? `Current period ends ${formatDate(subscription.currentPeriodEnd)}`
    : subscription?.trialEndsAt
      ? `Trial ends ${formatDate(subscription.trialEndsAt)}`
      : 'Billing period will appear when a payment provider is connected.';

  const limits = entitlements?.limits;
  const usage = entitlements?.usage;
  const memberUsage = usage ? usage.members + usage.pendingMemberSeats : 0;

  return <>
    <Card className="workspace-panel">
      <PanelHeading
        title="Plan & billing"
        description="Review your tenant subscription status, plan features, and measured usage."
        action={<Badge tone="brand">{formatPlan(plan)} · {status}</Badge>}
      />
      <div className="workspace-panel__body">
        {error ? <div className="workspace-empty-row"><CreditCard /><span><strong>Billing access is unavailable</strong><small>{error}</small></span></div> : <div className="workspace-empty-row"><CreditCard /><span><strong>{formatPlan(plan)} subscription</strong><small>{period}</small><small>Provider: {subscription?.provider ? formatPlan(subscription.provider) : 'Not connected'}</small>{subscription?.cancelAtPeriodEnd ? <small>Cancellation is scheduled for the end of the current period.</small> : null}{entitlements ? <small>CRM: {entitlements.features.crm ? 'Included' : 'Upgrade required'} · API: {entitlements.features.api ? 'Included' : 'Upgrade required'} · White-label: {entitlements.features.whiteLabel ? 'Included' : 'Upgrade required'}</small> : null}</span></div>}
      </div>
      <div className="workspace-plan-grid">
        <Usage label="Conversations this month" used={usage?.conversationsMonthly ?? 0} limit={limits?.conversationsMonthly} />
        <Usage label="AI agents" used={usage?.agents ?? 0} limit={limits?.agents} />
        <Usage label="Team seats" used={memberUsage} limit={limits?.members} suffix={usage?.pendingMemberSeats ? ` (${usage.pendingMemberSeats} pending)` : undefined} />
        <Usage label="AI tokens this month" used={usage?.tokensMonthly ?? 0} limit={limits?.tokensMonthly} />
        <Usage label="Knowledge storage" used={usage?.storageBytes ?? 0} limit={limits?.storageBytes} bytes />
      </div>
      <div className="workspace-panel__actions workspace-panel__actions--border">
        <Button variant="secondary" onClick={() => pushToast('Billing portal will open after a payment provider is connected', 'info')}>Manage billing</Button>
        <Button onClick={() => pushToast('Plan comparison opened', 'info')}>Compare plans</Button>
      </div>
    </Card>
    <Card className="workspace-upgrade-card"><Sparkles /><div><strong>Need more capacity?</strong><p>Upgrade limits without changing your agents, knowledge, integrations, or existing workspace data.</p></div><Button variant="secondary" onClick={() => pushToast('Plan comparison opened', 'info')}>View plans</Button></Card>
  </>;
}

function formatPlan(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString();
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  return `${(value / 1024 ** 3).toFixed(1)} GB`;
}

function PanelHeading({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <div className="workspace-panel__heading"><span><CreditCard /></span><div><h3>{title}</h3><p>{description}</p></div>{action}</div>;
}

function Usage({ label, used, limit, suffix, bytes = false }: { label: string; used: number; limit: number | null | undefined; suffix?: string; bytes?: boolean }) {
  const value = bytes ? formatBytes(used) : used.toLocaleString();
  const maximum = limit == null ? 'Unlimited' : bytes ? formatBytes(limit) : limit.toLocaleString();
  const width = limit == null || limit <= 0 ? '0%' : `${Math.min(100, Math.round((used / limit) * 100))}%`;
  return <div><small>{label}</small><strong>{value} / {maximum}{suffix ?? ''}</strong><span><i style={{ width }} /></span></div>;
}
