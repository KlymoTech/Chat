import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Switch } from '@/components/ui';
import { useToast } from '@/components/providers';
import { api } from '@/lib/api';
import type { Agent } from '@/types';

export function AgentStatusControl({ agent, onSaved, showEnrollmentLink = true }: { agent: Agent; onSaved: () => void; showEnrollmentLink?: boolean }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const { pushToast } = useToast();
  const change = async (active: boolean) => {
    setBusy(true); setError('');
    try {
      await api.agents.update(agent.id, { status: active ? 'active' : 'draft' });
      pushToast(active ? `${agent.name} is active` : `${agent.name} is now a draft. Replies are paused.`);
      onSaved();
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not update bot status'); }
    finally { setBusy(false); }
  };
  return <div className="agent-status-control">
    <Switch checked={agent.status === 'active'} disabled={busy || agent.status === 'training'} onChange={(active) => void change(active)}
      label={`${agent.name}: ${agent.status === 'active' ? 'Active' : 'Inactive (draft)'}`}
      description={busy ? 'Updating status...' : agent.purpose === 'education' ? 'Turn off to pause replies and keep your enrollments.' : 'Turn off to pause replies and save as a draft.'} />
    {error ? <div className="form-error" role="alert">{error}</div> : null}
    {showEnrollmentLink && agent.purpose === 'education' ? <Link className="button button--secondary button--sm" to={`/education/enrollments?agentId=${agent.id}`}>Manage enrollments</Link> : null}
  </div>;
}
