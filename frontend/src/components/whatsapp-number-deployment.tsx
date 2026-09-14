import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { useWorkspace } from '@/components/providers';
import { Button, Field, Badge } from '@/components/ui';
import type { WhatsAppConnection } from '@/types';

export function WhatsAppNumberDeployment({ agentId, onNumberChanged }: { agentId: string; onNumberChanged?: (number: string | null) => void }) {
  const { activeWorkspace } = useWorkspace();
  const [numbers, setNumbers] = useState<WhatsAppConnection[]>([]);
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [revision, setRevision] = useState(0);
  const current = numbers.find((number) => number.agentId === agentId);
  const next = numbers.find((number) => number.id === selected);
  useEffect(() => {
    let active = true;
    void api.integrations.whatsapp.status().then((status) => {
      if (!active) return;
      const items = status.connections ?? [];
      setNumbers(items); setSelected(items.find((number) => number.agentId === agentId)?.id ?? '');
    }).catch((failure: unknown) => { if (active) setError(failure instanceof Error ? failure.message : 'Could not load numbers'); });
    return () => { active = false; };
  }, [agentId, activeWorkspace?.id, revision]);
  const assign = async () => {
    const connectionId = selected || current?.id;
    if (!connectionId || busy) return;
    setBusy(true); setError(''); setNotice('');
    try {
      await api.integrations.whatsapp.assignNumber(connectionId, selected ? agentId : null);
      onNumberChanged?.(selected ? next?.displayPhoneNumber || null : null);
      setNotice(selected ? 'This number now routes new customer messages to this bot.' : 'Number released. You can deploy it to another bot.');
      setRevision((value) => value + 1);
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Could not update deployment'); }
    finally { setBusy(false); }
  };
  return <div className="whatsapp-manager">
    <h3>WhatsApp number for this bot</h3><Badge tone={current ? 'success' : 'neutral'}>{current ? current.displayPhoneNumber || current.phoneNumberId : 'No number assigned'}</Badge>
    {error ? <p role="alert">{error}</p> : null}{notice ? <p role="status">{notice}</p> : null}
    <Field label="Connected WhatsApp number" htmlFor="deploy-whatsapp-number" hint="One number routes to one bot. Other saved numbers remain available for your other bots."><select id="deploy-whatsapp-number" value={selected} disabled={busy} onChange={(event) => setSelected(event.target.value)}><option value="">No number assigned</option>{numbers.map((number) => <option key={number.id ?? number.phoneNumberId} value={number.id} disabled={number.status !== 'connected'}>{number.displayPhoneNumber || number.phoneNumberId} — {number.verifiedName}{number.agentId === agentId ? ' (this bot)' : number.agentId ? ' (assigned to another bot)' : ' (available)'}{number.status !== 'connected' ? ` — ${number.status}` : ''}</option>)}</select></Field>
    {next?.agentId && next.agentId !== agentId ? <p>This will move the selected number from its current bot to this bot.</p> : null}
    {selected !== (current?.id ?? '') ? <p>Changing deployment closes existing WhatsApp threads and cancels pending replies on the affected numbers. New messages use the new assignment.</p> : null}
    <div className="whatsapp-manager__actions"><Button disabled={busy || selected === (current?.id ?? '')} onClick={() => void assign()}>{busy ? 'Updating deployment…' : 'Apply number assignment'}</Button><a className="button button--secondary" href="/integrations">Add accounts or numbers</a></div>
  </div>;
}
