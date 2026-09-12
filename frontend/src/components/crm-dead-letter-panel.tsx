import { CircleAlert, RefreshCw } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Badge, Button, Card, EmptyState } from '@/components/ui';
import { crmDeadLetterApi, type CRMDeadLetterStatus } from '@/lib/crm-dead-letter-api';
import type { CRMConnectionView } from '@/lib/lead-crm-api';
import { relativeTime } from '@/lib/format';
import { useApi } from '@/lib/use-api';

interface CRMDeadLetterPanelProps {
  connections: CRMConnectionView[];
}

function statusTone(status: string): 'success' | 'warning' | 'neutral' {
  if (status === 'resolved') return 'success';
  if (status === 'open') return 'warning';
  return 'neutral';
}

export function CRMDeadLetterPanel({ connections }: CRMDeadLetterPanelProps) {
  const [status, setStatus] = useState<CRMDeadLetterStatus>('open');
  const [connectionId, setConnectionId] = useState('');
  const deadLetters = useApi(
    () => crmDeadLetterApi.list({ status, connectionId: connectionId || undefined }),
    [status, connectionId],
  );
  const connectionNames = useMemo(
    () => new Map(connections.map((connection) => [connection.id, connection.name])),
    [connections],
  );
  const rows = deadLetters.data ?? [];

  return <Card>
    <div className="page-heading page-heading--split">
      <div>
        <h3>CRM dead-letter queue</h3>
        <p>Review deliveries that exhausted automatic retries. Visibility is read-only here; recovery actions remain separate from the existing retry state machine.</p>
      </div>
      <Badge tone={rows.some((item) => item.status === 'open') ? 'warning' : 'neutral'}>
        {rows.filter((item) => item.status === 'open').length} open
      </Badge>
    </div>

    <div className="integration-toolbar">
      <label>
        Status
        <select aria-label="CRM dead-letter status" value={status} onChange={(event) => setStatus(event.target.value as CRMDeadLetterStatus)}>
          <option value="open">Open</option>
          <option value="resolved">Resolved</option>
          <option value="all">All</option>
        </select>
      </label>
      <label>
        CRM connection
        <select aria-label="CRM dead-letter connection" value={connectionId} onChange={(event) => setConnectionId(event.target.value)}>
          <option value="">All CRM connections</option>
          {connections.map((connection) => <option key={connection.id} value={connection.id}>{connection.name}</option>)}
        </select>
      </label>
      <Button variant="secondary" size="sm" icon={RefreshCw} disabled={deadLetters.loading} onClick={deadLetters.reload}>Refresh</Button>
    </div>

    {deadLetters.loading && !deadLetters.data ? <p>Loading CRM dead letters…</p> : deadLetters.error ? (
      <EmptyState
        icon={CircleAlert}
        title="CRM dead letters are unavailable"
        description={deadLetters.error}
        action={<Button variant="secondary" onClick={deadLetters.reload}>Try again</Button>}
      />
    ) : rows.length ? <div className="leads-table-wrap"><table className="leads-table">
      <thead><tr><th>Status</th><th>CRM</th><th>Provider</th><th>Reason</th><th>Lead / delivery</th><th>Created</th></tr></thead>
      <tbody>{rows.map((item) => <tr key={item.id}>
        <td><Badge tone={statusTone(item.status)}>{item.status}</Badge></td>
        <td>{connectionNames.get(item.connection_id) ?? item.connection_id}</td>
        <td>{item.provider}</td>
        <td><strong>{item.reason_code ?? 'unknown'}</strong>{item.reason_message ? <small>{item.reason_message}</small> : null}</td>
        <td><small>Lead {item.lead_id}</small><small>Delivery {item.delivery_id}</small></td>
        <td><time dateTime={item.created_at}>{relativeTime(item.created_at)}</time>{item.resolved_at ? <small>Resolved {relativeTime(item.resolved_at)}</small> : null}</td>
      </tr>)}</tbody>
    </table></div> : <EmptyState
      icon={CircleAlert}
      title={status === 'open' ? 'No open CRM dead letters' : 'No CRM dead letters found'}
      description={status === 'open' ? 'Automatic CRM delivery has no unresolved dead-letter items in this Workspace.' : 'Try another status or CRM connection filter.'}
    />}
  </Card>;
}
