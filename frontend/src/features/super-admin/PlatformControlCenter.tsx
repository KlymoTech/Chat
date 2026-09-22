import {
  Activity,
  AlertTriangle,
  GitBranch,
  RotateCcw,
  ShieldCheck,
  SlidersHorizontal,
  WalletCards,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Badge, Button, Card } from '@/components/ui';
import {
  platformAdminApi,
  type PlatformCapabilityCatalog,
  type PlatformCapabilityIntentAnalysis,
  type PlatformCapabilityOperation,
  type PlatformConfigVersion,
  type PlatformControlPolicy,
  type PlatformCostSnapshot,
  type PlatformDriftSnapshot,
  type PlatformFeatureIntentAnalysis,
  type PlatformFeatureState,
  type PlatformHealthSnapshot,
  type PlatformProviderDescriptor,
  type PlatformRuntimeChange,
  type PlatformSpecSnapshot,
} from '@/lib/platform-admin-api';
import './PlatformControlCenter.css';

interface PlatformControlCenterProps {
  catalog: PlatformCapabilityCatalog;
  canManage: boolean;
  onChangeCreated: (change: PlatformRuntimeChange) => void;
}

function label(value: string): string {
  return value.replaceAll('-', ' ').replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function statusTone(value: string): 'success' | 'warning' | 'danger' | 'neutral' | 'brand' {
  if (['healthy', 'completed', 'active', 'on', 'green'].includes(value)) return 'success';
  if (['degraded', 'unknown', 'waiting_approval', 'blue', 'amber'].includes(value)) return 'warning';
  if (['unhealthy', 'failed', 'red', 'critical'].includes(value)) return 'danger';
  if (value === 'locked') return 'brand';
  return 'neutral';
}

function operationLabel(operation: PlatformCapabilityOperation): string {
  if (operation === 'destroy') return 'Destroy infrastructure';
  if (operation === 'stop') return 'Stop infrastructure';
  if (operation === 'disable') return 'Disable capability';
  if (operation === 'enable') return 'Enable capability';
  return 'Switch provider';
}

function planSummary(
  analysis: PlatformCapabilityIntentAnalysis | PlatformFeatureIntentAnalysis,
): string {
  const plan = analysis.analysis.plan;
  const impacted = analysis.analysis.impacted_capabilities.join(', ') || 'none';
  const steps = plan.steps.join(' → ') || 'No deployment steps';
  return [
    `Action: ${plan.action}`,
    `Classification: ${plan.classification}`,
    `Approval required: ${plan.requires_approval ? 'YES' : 'NO'}`,
    `Impacted capabilities: ${impacted}`,
    `Steps: ${steps}`,
  ].join('\n');
}

function changeKey(scope: string): string {
  return `control-center-${Date.now()}-${scope}`.replace(/[^A-Za-z0-9._:-]/g, '-').slice(0, 128);
}

export function PlatformControlCenter({
  catalog,
  canManage,
  onChangeCreated,
}: PlatformControlCenterProps) {
  const [snapshot, setSnapshot] = useState<PlatformSpecSnapshot | null>(null);
  const [providers, setProviders] = useState<PlatformProviderDescriptor[]>([]);
  const [policies, setPolicies] = useState<PlatformControlPolicy[]>([]);
  const [features, setFeatures] = useState<PlatformFeatureState[]>([]);
  const [health, setHealth] = useState<PlatformHealthSnapshot | null>(null);
  const [drift, setDrift] = useState<PlatformDriftSnapshot | null>(null);
  const [cost, setCost] = useState<PlatformCostSnapshot | null>(null);
  const [versions, setVersions] = useState<PlatformConfigVersion[]>([]);
  const [providerDrafts, setProviderDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  const policyByCapability = useMemo(
    () => Object.fromEntries(policies.map((item) => [item.capability_id, item])),
    [policies],
  );
  const providersByCapability = useMemo(() => {
    const result: Record<string, PlatformProviderDescriptor[]> = {};
    providers.forEach((item) => {
      (result[item.capability_id] ??= []).push(item);
    });
    return result;
  }, [providers]);

  const refresh = async () => {
    const environment = catalog.environment;
    const [nextSnapshot, nextProviders, nextPolicies, nextFeatures, nextHealth, nextDrift, nextCost, nextVersions] =
      await Promise.all([
        platformAdminApi.runtimeSpec(environment),
        platformAdminApi.runtimeProviders(),
        platformAdminApi.runtimePolicies(),
        platformAdminApi.runtimeFeatures(environment),
        platformAdminApi.runtimeHealth(environment),
        platformAdminApi.runtimeDrift(environment),
        platformAdminApi.runtimeCost(environment),
        platformAdminApi.runtimeConfigVersions(environment),
      ]);
    setSnapshot(nextSnapshot);
    setProviders(nextProviders);
    setPolicies(nextPolicies);
    setFeatures(nextFeatures);
    setHealth(nextHealth);
    setDrift(nextDrift);
    setCost(nextCost);
    setVersions(nextVersions);
    setProviderDrafts((current) => {
      const next = { ...current };
      catalog.capabilities.forEach((capability) => {
        next[capability.definition.capability_id] ??= capability.provider;
      });
      return next;
    });
  };

  useEffect(() => {
    let active = true;
    setError('');
    void refresh().catch((reason) => {
      if (active) setError(reason instanceof Error ? reason.message : 'Control-center data could not be loaded');
    });
    return () => { active = false; };
    // catalog revision changes only after verified activation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog.environment, catalog.revision]);

  const executeCapabilityIntent = async (
    capabilityId: string,
    operation: PlatformCapabilityOperation,
    provider?: string | null,
  ) => {
    if (!canManage) return;
    setBusy(`${capabilityId}:${operation}`);
    setError('');
    try {
      const planned = await platformAdminApi.planRuntimeCapabilityChange(capabilityId, { operation, provider });
      if (planned.analysis.blockers.length) {
        setError(`Change blocked: ${planned.analysis.blockers.join(', ')}`);
        return;
      }
      const warning = operation === 'destroy'
        ? '\n\nDESTROY is intentionally separate from disable. The approved executor may remove provisioned infrastructure only after dependencies have been detached.'
        : operation === 'stop'
          ? '\n\nSTOP affects infrastructure lifecycle, not just application routing.'
          : '';
      if (!window.confirm(`${planSummary(planned)}${warning}\n\nCreate this change request?`)) return;
      const reason = window.prompt('Reason / change ticket for this platform change:')?.trim() ?? '';
      if (reason.length < 5) return;
      const created = await platformAdminApi.createRuntimeCapabilityChange(capabilityId, {
        operation,
        provider,
        reason,
        idempotency_key: changeKey(`${capabilityId}-${operation}`),
      });
      onChangeCreated(created);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Platform capability change could not be created');
    } finally {
      setBusy('');
    }
  };

  const executeFeatureIntent = async (feature: PlatformFeatureState) => {
    if (!canManage) return;
    const desired = !feature.enabled;
    setBusy(`feature:${feature.definition.feature_id}`);
    setError('');
    try {
      const planned = await platformAdminApi.planRuntimeFeatureChange(feature.definition.feature_id, desired);
      if (planned.analysis.blockers.length) {
        setError(`Change blocked: ${planned.analysis.blockers.join(', ')}`);
        return;
      }
      if (!window.confirm(`${planSummary(planned)}\n\nCreate this feature change request?`)) return;
      const reason = window.prompt('Reason / change ticket for this feature change:')?.trim() ?? '';
      if (reason.length < 5) return;
      const created = await platformAdminApi.createRuntimeFeatureChange(feature.definition.feature_id, {
        enabled: desired,
        reason,
        idempotency_key: changeKey(`feature-${feature.definition.feature_id}`),
      });
      onChangeCreated(created);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Feature change could not be created');
    } finally {
      setBusy('');
    }
  };

  return <>
    <Card className="workspace-panel platform-control-overview">
      <div className="card-heading">
        <div>
          <h3>Platform Control Center</h3>
          <p>Desired state, evidence-based actual state, dependencies, policy, approval and rollback.</p>
        </div>
        <Badge tone={statusTone(health?.overall ?? 'unknown')}>{label(health?.overall ?? 'Unknown')}</Badge>
      </div>
      {error ? <div className="platform-control-alert"><AlertTriangle /><span>{error}</span></div> : null}
      <div className="platform-control-summary">
        <div><small>Environment</small><strong>{label(catalog.environment)}</strong><small>{catalog.profile}</small></div>
        <div><small>Desired revision</small><strong>v{snapshot?.spec.metadata.revision ?? catalog.revision}</strong><small>{snapshot?.digest.slice(0, 12) ?? 'loading'}…</small></div>
        <div><small>Health evidence</small><strong>{health ? `${health.healthy} healthy` : 'Loading'}</strong><small>{health ? `${health.unknown} unobserved` : '—'}</small></div>
        <div><small>Drift</small><strong>{drift?.drift_count ?? '—'}</strong><small>{drift ? `${drift.unobserved_count} awaiting observation` : '—'}</small></div>
        <div><small>Reported monthly cost</small><strong>{cost ? `$${cost.reported_monthly_usd.toFixed(2)}` : '—'}</strong><small>{cost ? `${cost.unreported_capabilities.length} without cost evidence` : '—'}</small></div>
      </div>
    </Card>

    <Card className="workspace-panel">
      <div className="card-heading">
        <div><h3>Capabilities & providers</h3><p>Disable, stop and destroy are separate operations. Locked platform invariants cannot be switched off.</p></div>
        <SlidersHorizontal />
      </div>
      <div className="platform-capability-table" role="table" aria-label="Platform capabilities">
        <div className="platform-capability-row platform-capability-row--head" role="row">
          <span>Capability</span><span>Desired</span><span>Actual</span><span>Provider</span><span>Policy</span><span>Controls</span>
        </div>
        {catalog.capabilities.map((capability) => {
          const id = capability.definition.capability_id;
          const policy = policyByCapability[id];
          const options = providersByCapability[id] ?? [];
          const selectedProvider = providerDrafts[id] ?? capability.provider;
          const isBusy = busy.startsWith(`${id}:`);
          return <div className="platform-capability-row" role="row" key={id}>
            <span className="platform-capability-name">
              <strong>{label(id)}</strong>
              <small>{capability.definition.description}</small>
              <small>{capability.definition.depends_on.length ? `Depends on: ${capability.definition.depends_on.join(', ')}` : 'No declared dependency'}</small>
            </span>
            <span><Badge tone={capability.desired_state === 'on' ? 'success' : 'neutral'}>{capability.desired_state.toUpperCase()}</Badge></span>
            <span>
              <strong>{label(capability.actual_state)}</strong>
              <small>{label(capability.health)}</small>
              {capability.fallback_active ? <Badge tone="warning">Fallback active</Badge> : null}
            </span>
            <span>
              <select
                aria-label={`${id} provider`}
                value={selectedProvider}
                disabled={!canManage || !policy?.mutable || options.length < 2 || isBusy}
                onChange={(event) => setProviderDrafts((current) => ({ ...current, [id]: event.target.value }))}
              >
                {options.map((option) => <option value={option.provider} key={option.provider}>
                  {option.label}{option.fallback ? ' · fallback' : ''}
                </option>)}
              </select>
              <small>Observed: {capability.observed_provider ? label(capability.observed_provider) : 'not reported'}</small>
            </span>
            <span>
              <Badge tone={statusTone(policy?.risk_class ?? (capability.definition.locked ? 'locked' : 'unknown'))}>
                {label(policy?.risk_class ?? (capability.definition.locked ? 'locked' : 'unknown'))}
              </Badge>
              <small>{policy ? label(policy.switch_class) : 'Loading policy'}</small>
            </span>
            <span className="platform-control-actions">
              {capability.definition.locked || !policy?.mutable
                ? <Badge tone="brand"><ShieldCheck /> Required</Badge>
                : <>
                  {policy.allowed_operations.includes('switch') && selectedProvider !== capability.provider
                    ? <Button variant="secondary" disabled={!canManage || isBusy} onClick={() => void executeCapabilityIntent(id, 'switch', selectedProvider)}>Review switch</Button>
                    : null}
                  {policy.allowed_operations.includes(capability.desired_state === 'on' ? 'disable' : 'enable')
                    ? <Button
                        variant="secondary"
                        disabled={!canManage || isBusy}
                        onClick={() => void executeCapabilityIntent(
                          id,
                          capability.desired_state === 'on' ? 'disable' : 'enable',
                          capability.desired_state === 'off' ? selectedProvider : undefined,
                        )}
                      >
                        {capability.desired_state === 'on' ? 'Disable' : 'Enable'}
                      </Button>
                    : null}
                  {policy.allowed_operations.includes('stop')
                    ? <Button variant="secondary" disabled={!canManage || isBusy} onClick={() => void executeCapabilityIntent(id, 'stop')}>Stop</Button>
                    : null}
                  {policy.allowed_operations.includes('destroy')
                    ? <Button variant="secondary" disabled={!canManage || isBusy} onClick={() => void executeCapabilityIntent(id, 'destroy')}>Destroy</Button>
                    : null}
                </>}
            </span>
          </div>;
        })}
      </div>
      {!canManage ? <p className="platform-control-note">Read-only access: platform.runtime.manage is required to create changes.</p> : null}
    </Card>

    <Card className="workspace-panel">
      <div className="card-heading"><div><h3>Application features</h3><p>Feature changes still go through server-side dependency validation and production approval policy.</p></div><Activity /></div>
      <div className="platform-feature-grid">
        {features.map((feature) => <div key={feature.definition.feature_id}>
          <span><strong>{feature.definition.label}</strong><small>{feature.definition.depends_on.length ? `Requires ${feature.definition.depends_on.join(', ')}` : 'Independent feature flag'}</small></span>
          <Badge tone={feature.enabled ? 'success' : 'neutral'}>{feature.enabled ? 'ON' : 'OFF'}</Badge>
          <Button
            variant="secondary"
            disabled={!canManage || busy === `feature:${feature.definition.feature_id}`}
            onClick={() => void executeFeatureIntent(feature)}
          >
            Review {feature.enabled ? 'OFF' : 'ON'}
          </Button>
        </div>)}
      </div>
    </Card>

    <div className="platform-control-grid">
      <Card className="workspace-panel">
        <div className="card-heading"><div><h3>Drift & observation</h3><p>Unknown state is shown as missing evidence, never as healthy.</p></div><GitBranch /></div>
        {drift?.findings.length
          ? <div className="agent-row-list">{drift.findings.map((finding) => <div className="agent-row" key={`${finding.capability_id}-${finding.kind}`}>
              <span className="agent-row__main"><strong>{label(finding.capability_id)}</strong><small>{finding.message}</small></span>
              <Badge tone={statusTone(finding.severity)}>{finding.desired} → {finding.observed}</Badge>
            </div>)}</div>
          : <p className="platform-control-note">{drift ? `No confirmed drift. ${drift.unobserved_count} capabilities still require observation evidence.` : 'Loading drift evidence…'}</p>}
      </Card>

      <Card className="workspace-panel">
        <div className="card-heading"><div><h3>FinOps evidence</h3><p>Only reported cost evidence is totaled; missing values are never guessed.</p></div><WalletCards /></div>
        <div className="platform-control-cost"><strong>{cost ? `$${cost.reported_monthly_usd.toFixed(2)} / month` : 'Loading…'}</strong><small>{cost ? `Reported: ${cost.reported_capabilities.length} · Missing: ${cost.unreported_capabilities.length}` : '—'}</small></div>
      </Card>
    </div>

    <Card className="workspace-panel">
      <div className="card-heading"><div><h3>Configuration versions</h3><p>Verified deployment targets become active only after completion evidence. Previous versions remain rollback evidence.</p></div><RotateCcw /></div>
      <div className="agent-row-list">
        {versions.slice(0, 10).map((version) => <div className="agent-row" key={version.id}>
          <span className="agent-row__main"><strong>Revision v{version.revision}</strong><small>{version.digest.slice(0, 16)}… · {new Date(version.created_at).toLocaleString()}</small></span>
          <Badge tone={version.active ? 'success' : 'neutral'}>{version.active ? 'ACTIVE' : 'HISTORY'}</Badge>
        </div>)}
        {!versions.length ? <p className="platform-control-note">No persisted deployment versions yet. The declared runtime configuration is currently the bootstrap desired state.</p> : null}
      </div>
    </Card>
  </>;
}
