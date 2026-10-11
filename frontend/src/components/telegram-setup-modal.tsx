import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Button, Field, Modal } from '@/components/ui';
import { api } from '@/lib/api';
import { leadCrmApi, type ChannelConnectionView, type TelegramBotInfo } from '@/lib/lead-crm-api';
import { useApi } from '@/lib/use-api';

export function trustedTelegramUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && url.hostname === 't.me' && !url.port && !url.username && !url.password && /^\/[A-Za-z0-9_]{5,32}$/.test(url.pathname) && !url.hash;
  } catch { return false; }
}

export function TelegramStudentLink({ bot }: { bot?: TelegramBotInfo | null }) {
  if (!bot || !trustedTelegramUrl(bot.studentUrl)) return null;
  return <div className="connection-details"><span>Bot</span><strong>{bot.botName}</strong><span>Username</span><strong>@{bot.botUsername}</strong><span>Student bot</span><a href={bot.studentUrl} target="_blank" rel="noopener noreferrer">{bot.studentUrl}</a></div>;
}

export function TelegramSetupModal({ connections, canManage, onClose, onChanged }: { connections: ChannelConnectionView[]; canManage: boolean; onClose: () => void; onChanged: () => void; }) {
  const agents = useApi(() => api.agents.list());
  const available = (agents.data ?? []).filter(agent => agent.appearance.deploymentChannel === 'telegram');
  const telegramConnections = useMemo(() => connections.filter(connection => connection.provider === 'telegram'), [connections]);
  const [agentId, setAgentId] = useState('');
  const [name, setName] = useState('Telegram bot');
  const [botToken, setBotToken] = useState('');
  // Manage opens in a neutral state. Staff explicitly select an agent or bot.
  const [selectedId, setSelectedId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const selected = telegramConnections.find(connection => connection.id === selectedId);
  const selectedBot = selected?.configuration.telegram as TelegramBotInfo | undefined;
  useEffect(() => {
    // Selecting an existing bot displays its persisted agent binding.
    if (selected?.agent_id) {
      setAgentId(selected.agent_id);
    }
  }, [agentId, available, selected?.agent_id]);

  async function connect() {
    setBusy(true); setError('');
    try { const connected = await leadCrmApi.connectTelegramBot({ agentId, name: name.trim(), botToken }); setSelectedId(connected.id); setBotToken(''); onChanged(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not connect Telegram.'); }
    finally { setBusy(false); }
  }
  async function testConnection() {
    if (!selected) return;
    setBusy(true); setError('');
    try { await leadCrmApi.testChannelConnection(selected.id); onChanged(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Telegram health check failed.'); }
    finally { setBusy(false); }
  }
  async function disconnect() {
    if (!selected) return;
    setBusy(true); setError('');
    try { await leadCrmApi.disconnectTelegramConnection(selected.id); setSelectedId(''); onChanged(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not disconnect Telegram.'); }
    finally { setBusy(false); }
  }

  return <Modal open title="Telegram" description="Connect a normal Telegram bot to an agent." onClose={onClose} size="md" footer={selected && selected.status !== 'disabled' ? <><Button variant="secondary" disabled={!canManage || busy} onClick={() => void testConnection()}>{busy ? 'Working…' : 'Test connection'}</Button><Button disabled={!canManage || busy} onClick={() => void disconnect()}>{busy ? 'Working…' : 'Disconnect'}</Button></> : <Button disabled={!canManage || busy || !agentId || !name.trim() || !botToken.trim()} onClick={() => void connect()}>{busy ? 'Connecting…' : 'Connect'}</Button>}>
    <div className="connection-setup">
      <Field label="Agent" htmlFor="telegram-agent" hint="Only agents assigned to Telegram are listed."><select className="telegram-picker-select" id="telegram-agent" disabled={busy} value={agentId} onChange={event => { setAgentId(event.target.value); setSelectedId(''); setError(''); }}><option value="">Select an agent</option>{available.map(agent => <option value={agent.id} key={agent.id}>{agent.name}</option>)}</select></Field>
      {!!telegramConnections.length && <Field label="Connected bot" htmlFor="telegram-account"><select className="telegram-picker-select" id="telegram-account" disabled={busy} value={selectedId} onChange={event => { setSelectedId(event.target.value); setError(''); }}><option value="">Connect another bot</option>{telegramConnections.map(connection => { const bot = connection.configuration.telegram as TelegramBotInfo | undefined; return <option value={connection.id} key={connection.id}>{bot?.botUsername ? `@${bot.botUsername}` : connection.name} — {connection.status}</option>; })}</select></Field>}
      {!selected && <><Field label="Connection name" htmlFor="telegram-name" hint="Visible only to workspace staff."><input id="telegram-name" value={name} maxLength={160} onChange={event => setName(event.target.value)} disabled={busy} /></Field><Field label="BotFather token" htmlFor="telegram-token" hint="Saved encrypted. It is never shown again."><input id="telegram-token" type="password" autoComplete="off" value={botToken} onChange={event => setBotToken(event.target.value)} disabled={busy} /></Field><p>talktobot validates the bot, securely registers its webhook, and then uses the existing course and reply pipeline. Students only need to message the bot after staff add their numeric Telegram ID to the student record.</p></>}
      {selected && <><p role="status">Status: {selected.status}. Last inbound event: {selected.last_event_at ? new Date(selected.last_event_at).toLocaleString() : 'not received yet'}.</p><TelegramStudentLink bot={selectedBot} /></>}
      {agents.error && <p role="alert">Could not load agents.</p>}
      {!agents.loading && !agents.error && !available.length && <p>Create a Telegram agent first. <Link to="/agents" onClick={onClose}>Go to Agents</Link></p>}
      {error && <p role="alert" className="catalog-notice catalog-notice--error">{error}</p>}
    </div>
  </Modal>;
}
