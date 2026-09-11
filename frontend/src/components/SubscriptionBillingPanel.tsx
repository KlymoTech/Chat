import { CreditCard, Sparkles } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { useToast } from '@/components/providers';
import { Badge, Button, Card } from '@/components/ui';
import { billingApi, type SubscriptionStatus, type TenantSubscription } from '@/lib/billing-api';
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
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    setError('');
    void billingApi.getSubscription(workspace.plan)
      .then((value) => { if (active) setSubscription(value); })
      .catch((reason) => {
        if (!active) return;
        const message = reason instanceof Error ? reason.message : 'Billing information could not be loaded';
        setError(message);
        pushToast(message, 'error');
      });
    return () => { active = false; };
  }, [pushToast, workspace.id, workspace.plan]);

  const plan = subscription?.plan ?? workspace.plan;
  const status = subscription ? statusLabels[subscription.status] : 'Loading';
  const period = subscription?.currentPeriodEnd
    ? `Current period ends ${formatDate(subscription.currentPeriodEnd)}`
    : subscription?.trialEndsAt
      ? `Trial ends ${formatDate(subscription.trialEndsAt)}`
      : 'Billing period will appear when a payment provider is connected.';

  return <>
    <Card className="workspace-panel">
      <PanelHeading
        title="Plan & billing"
        description="Review your tenant subscription status and existing workspace usage."
        action={<Badge tone="brand">{formatPlan(plan)} · {status}</Badge>}
      />
      <div className="workspace-panel__body">
        {error ? <div className="workspace-empty-row"><CreditCard /><span><strong>Billing access is unavailable</strong><small>{error}</small></span></div> : <div className="workspace-empty-row"><CreditCard /><span><strong>{formatPlan(plan)} subscription</strong><small>{period}</small><small>Provider: {subscription?.provider ? formatPlan(subscription.provider) : 'Not connected'}</small>{subscription?.cancelAtPeriodEnd ? <small>Cancellation is scheduled for the end of the current period.</small> : null}</span></div>}
      </div>
      <div className="workspace-plan-grid">
        <Usage label="Conversations" value="1,892 / 5,000" width="38%" />
        <Usage label="AI agents" value="4 / 10" width="40%" />
        <Usage label="Team members" value={`${workspace.memberCount} / 20`} width="25%" />
      </div>
      <div className="workspace-panel__actions workspace-panel__actions--border">
        <Button variant="secondary" onClick={() => pushToast('Billing portal will open after a payment provider is connected', 'info')}>Manage billing</Button>
        <Button onClick={() => pushToast('Plan comparison opened', 'info')}>Compare plans</Button>
      </div>
    </Card>
    <Card className="workspace-upgrade-card"><Sparkles /><div><strong>Need more capacity?</strong><p>Upgrade limits without changing your agents, knowledge, or integrations.</p></div><Button variant="secondary" onClick={() => pushToast('Plan comparison opened', 'info')}>View plans</Button></Card>
  </>;
}

function formatPlan(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString();
}

function PanelHeading({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <div className="workspace-panel__heading"><span><CreditCard /></span><div><h3>{title}</h3><p>{description}</p></div>{action}</div>;
}

function Usage({ label, value, width }: { label: string; value: string; width: string }) {
  return <div><small>{label}</small><strong>{value}</strong><span><i style={{ width }} /></span></div>;
}
