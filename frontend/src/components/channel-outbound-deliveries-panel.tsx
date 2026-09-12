import { Activity, CircleAlert, RefreshCw } from 'lucide-react';
import { useState } from 'react';
import { Badge, Button, Card, EmptyState } from '@/components/ui';
import { channelDeliveriesApi } from '@/lib/channel-deliveries-api';
import { relativeTime } from '@/lib/format';
import type { ChannelConnectionView } from '@/lib/lead-crm-api';
import { useApi } from '@/lib/use-api';

function statusTone(status: string): 'success' | 'warning' | 'brand' | 'neutral' {
  if (status === 'sent') return 'success';
  if (['rejected', 'reconnect_required', 'dispatch_failed'].includes(status)) return 'warning';
  if (['queued', 'processing', 'failed'].includes(status)) return 'brand';
  return 'neutral';
}

interface ChannelOutboundDeliveriesPanelProps {
  connections: ChannelConnectionView[];
}

export function ChannelOutboundDeliveriesPanel({ connections }: ChannelOutboundDeliveriesPanelProps) {
  const [connectionId, setConnectionId] = useState('');
  const [status, setStatus] = useState('');
  const deliveries = useApi(
    () => channelDeliveriesApi.list({
      connectionId: connectionId || undefined,
      status: status || undefined,
      limit: 100,
    }),
    [connectionId, status],
  );

  return <Card>
    <div className="page-heading page-heading--split">
      <div>
        <h3>Channel outbound deliveries</h3>
        <p>Inspect safe Workspace delivery status, attempts, retry timing, and normalized failure evidence. Recipient identities, provider message IDs, message text, raw provider errors, payloads, and credentials are not exposed.</p>
      </div>
      <Button variant="secondary" size="sm" icon={RefreshCw} disabled={deliveries.loading} onClick={deliveries.reload}>Refresh deliveries</Button>
    </div>

    <div className="integration-toolbar">
      <label>
        Channel connection
        <select aria-label="Channel delivery connection" value={connectionId} onChange={(event) => setConnectionId(event.target.value)}>
          <option value="">All Workspace connections</option>
          {connections.map((connection) => <option key={connection.id} value={connection.id}>{connection.name} · {connection.provider}</option>)}
        </select>
      </label>
      <label>
        Delivery status
        <select aria-label="Channel delivery status" value={status} onChange={(event) => setStatus(event.target.value)}>
          <option value="">All statuses</option>
          <option value="queued">Queued</option>
          <option value="processing">Processing</option>
          <option value="failed">Retrying</option>
          <option value="sent">Sent</option>
          <option value="rejected">Rejected</option>
          <option value="reconnect_required">Reconnect required</option>
          <option value="dispatch_failed">Dispatch failed</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </label>
    </div>

    {deliveries.loading && !deliveries.data ? <p>Loading channel outbound deliveries…</p> : deliveries.error && !deliveries.data ? <EmptyState
      icon={CircleAlert}
      title="Channel outbound deliveries are unavailable"
      description={deliveries.error}
      action={<Button variant="secondary" onClick={deliveries.reload}>Try again</Button>}
    /> : !deliveries.data?.length ? <EmptyState
      icon={Activity}
      title="No outbound delivery evidence found"
      description="No provider-neutral outbound deliveries match the selected Workspace filters yet."
    /> : <div className="leads-table-wrap"><table className="leads-table">
      <thead><tr><th>Updated</th><th>Connection</th><th>Provider</th><th>Status</th><th>Attempts</th><th>Next retry</th><th>Normalized error</th><th>Message ref</th></tr></thead>
      <tbody>{deliveries.data.map((delivery) => <tr key={delivery.id}>
        <td><strong>{new Date(delivery.updated_at).toLocaleString()}</strong><small>{relativeTime(delivery.updated_at)}</small></td>
        <td>{delivery.connection_name ?? 'Disconnected historical delivery'}</td>
        <td>{delivery.provider}</td>
        <td><Badge tone={statusTone(delivery.status)}>{delivery.status}</Badge></td>
        <td><small>Provider {delivery.attempt_count}</small><small>Dispatch {delivery.dispatch_attempts}</small></td>
        <td>{delivery.next_dispatch_at ? <><strong>{new Date(delivery.next_dispatch_at).toLocaleString()}</strong><small>{relativeTime(delivery.next_dispatch_at)}</small></> : '—'}</td>
        <td>{delivery.error_code ? <code>{delivery.error_code}</code> : '—'}</td>
        <td><code>{delivery.message_id}</code></td>
      </tr>)}</tbody>
    </table></div>}
  </Card>;
}
