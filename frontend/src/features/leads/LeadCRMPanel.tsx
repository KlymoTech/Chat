import { ExternalLink, RefreshCw } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Badge, Button, Modal } from '@/components/ui';
import { CRMDeliveryAttempts } from '@/components/crm-delivery-attempts';
import { useToast } from '@/components/providers';
import { getVerificationView } from '@/lib/crm-delivery-status';
import { leadCrmApi } from '@/lib/lead-crm-api';
import { useApi } from '@/lib/use-api';
import { relativeTime } from '@/lib/format';
import type { Lead } from '@/types';
import { LeadIdentity } from './LeadDialogs';
import { label } from './presentation';

export function LeadCRMPanel({ lead, canSync }: { lead: Lead; canSync: boolean }) {
  const deliveries = useApi(() => leadCrmApi.deliveriesForLead(lead.id), [lead.id]);
  const activity = useApi(() => leadCrmApi.activityForLead(lead.id), [lead.id]);
  const [syncOpen, setSyncOpen] = useState(false); const [retrying, setRetrying] = useState('');
  const { pushToast } = useToast();
  async function retry(id: string) { setRetrying(id); try { const result = await leadCrmApi.retryDelivery(id); pushToast(result.acknowledged_at ? 'CRM verification queued; the acknowledged write will not be resent' : 'CRM delivery queued for retry'); deliveries.reload(); activity.reload(); } catch (e) { pushToast(e instanceof Error ? e.message : 'Could not retry CRM delivery', 'error'); } finally { setRetrying(''); } }
  return <section className="ld-crm"><div className="ld-section-title"><h3><RefreshCw />CRM workflow</h3><button type="button" className="icon-button" title="Refresh CRM status" aria-label="Refresh CRM status" onClick={() => { deliveries.reload(); activity.reload(); }}><RefreshCw /></button></div>
    {deliveries.loading ? <p role="status">Loading CRM deliveries…</p> : deliveries.error ? <p role="alert">Could not load CRM deliveries: {deliveries.error}<Button variant="secondary" onClick={deliveries.reload}>Retry</Button></p> : deliveries.data?.length ? deliveries.data.map((delivery) => {
      const proof = getVerificationView(delivery);
      return <article className="ld-crm-record" key={delivery.id}><div><strong>{label(delivery.provider)}</strong><Badge tone={proof.proved ? 'success' : proof.error ? 'warning' : 'neutral'}>{proof.label}</Badge></div><p>External record ID: <code>{delivery.external_record_id || 'Not assigned yet'}</code></p><small>Delivery: {label(delivery.status)} · {delivery.attempt_count} write attempts</small>{delivery.last_error_message && <p role="status">{delivery.last_error_message}</p>}{proof.error && <small>{proof.error}</small>}<small>Provider ACK: {delivery.acknowledged_at ? relativeTime(delivery.acknowledged_at) : 'Not received'} · Read-back attempts: {proof.attempts}</small>{proof.nextAttempt && <small>Next check: {new Date(proof.nextAttempt).toLocaleString()}</small>}<div className="ld-crm-actions">{canSync && proof.retryable && <Button variant="secondary" size="sm" disabled={Boolean(retrying)} onClick={() => void retry(delivery.id)}>{proof.retryLabel}</Button>}<CRMDeliveryAttempts deliveryId={delivery.id} attemptCount={delivery.attempt_count} /></div></article>;
    }) : <p className="ld-muted">No CRM deliveries yet. Queued, acknowledged and verified states are reported separately.</p>}
    <Button className="ld-full" icon={RefreshCw} disabled={!canSync} onClick={() => setSyncOpen(true)}>{deliveries.data?.length ? 'Re-sync to CRM' : 'Sync to CRM'}</Button>
    {!canSync && <small>CRM management permission is required to queue a sync.</small>}
    <details className="ld-audit"><summary>Lead activity</summary>{activity.loading ? <p role="status">Loading activity…</p> : activity.error ? <p role="alert">{activity.error}</p> : activity.data?.length ? activity.data.slice().reverse().map((item) => <p key={item.id}><strong>{label(item.event_type)}</strong><small>{relativeTime(item.occurred_at)}</small></p>) : <p>No activity recorded yet.</p>}</details>
    {syncOpen && <LeadSyncDialog lead={lead} onClose={() => setSyncOpen(false)} onQueued={() => { setSyncOpen(false); deliveries.reload(); activity.reload(); }} />}
  </section>;
}
export function LeadSyncDialog({ lead, onClose, onQueued }: { lead: Lead; onClose: () => void; onQueued: () => void }) {
  const connections = useApi(() => leadCrmApi.connections());
  const [selectedId, setSelectedId] = useState('');
  const selected = connections.data?.find((item) => item.id === selectedId) ?? connections.data?.[0];
  const mappings = useApi(() => selected ? leadCrmApi.mappings(selected.id) : Promise.resolve([]), [selected?.id]);
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const { pushToast } = useToast();
  async function sync() { setBusy(true); setError(''); try { await leadCrmApi.syncLead(lead.id, 'manual-ui'); pushToast('CRM synchronization queued; delivery is not yet verified'); onQueued(); } catch (e) { setError(e instanceof Error ? e.message : 'Could not queue CRM synchronization'); } finally { setBusy(false); } }
  return <Modal open onClose={onClose} closeDisabled={busy} title="Sync lead to CRM" description="Review connected CRM configuration before queuing this lead." size="lg" bodyClassName="ld-dialog" footer={<><Button variant="secondary" onClick={onClose} disabled={busy}>Cancel</Button><Button icon={RefreshCw} onClick={() => void sync()} disabled={busy || connections.loading || Boolean(connections.error) || !connections.data?.length}>{busy ? 'Queuing…' : 'Sync lead'}</Button></>}>
    <LeadIdentity lead={lead} /><div className="ld-section-title"><h3 className="ld-label">Connected CRM</h3><Link to="/integrations">+ Add integration</Link></div>
    {connections.loading ? <p role="status">Loading connected CRMs…</p> : connections.error ? <p role="alert">{connections.error}<Button variant="secondary" onClick={connections.reload}>Retry</Button></p> : connections.data?.length ? <div className="ld-connection-cards" role="group" aria-label="Preview CRM configuration">{connections.data.map((item) => <button type="button" key={item.id} aria-pressed={selected?.id === item.id} onClick={() => setSelectedId(item.id)}><strong>{item.name}</strong><small>{label(item.provider)} · {label(item.status)}</small><small>{item.environment}</small></button>)}</div> : <p>No CRM is connected. Connect a CRM before synchronizing leads.</p>}
    <h3 className="ld-label">Configured object and field mapping</h3>{mappings.loading ? <p role="status">Loading field mappings…</p> : mappings.error ? <p role="alert">{mappings.error}<Button variant="secondary" onClick={mappings.reload}>Retry</Button></p> : mappings.data?.length ? mappings.data.map((mapping) => <details className="ld-mapping" key={mapping.object_name} open><summary>{mapping.object_name} <Badge>{label(mapping.status)}</Badge></summary><pre>{JSON.stringify(mapping.mapping, null, 2)}</pre></details>) : <p className="ld-muted">No saved mapping is available for this connection.</p>}
    <Link className="ld-config-link" to="/crm-workflow"><ExternalLink />View full mapping and routing configuration</Link><p className="ld-notice">Sync uses the existing workspace CRM routing, object mapping and duplicate-handling rules. Choosing a card previews its configuration; it does not override routing. A queued request is not proof of a delivered or verified CRM record.</p>{error && <p className="form-error" role="alert">{error}</p>}
  </Modal>;
}
