import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth, useToast, useWorkspace } from '@/components/providers';
import { AgentsPage, CreateAgentModal } from '@/pages/AgentsPage';
import { canUseDashboardCapability } from './dashboardPermissions';

/** Deep-link into the existing creation workflow without copying business logic. */
export function AgentsRoutePage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const { pushToast } = useToast();
  const { session } = useAuth();
  const { activeWorkspace } = useWorkspace();
  if (params.get('create') !== '1') return <AgentsPage />;
  const close = () => {
    const next = new URLSearchParams(params);
    next.delete('create');
    setParams(next, { replace: true });
  };
  if (!canUseDashboardCapability({ role: session?.user.role, permissions: activeWorkspace?.permissions }, 'agents.create')) {
    return <div className="page"><h2>Agent creation access required</h2><p>Your workspace role cannot create an agent.</p><button type="button" className="button button--secondary" onClick={close}>Back to agents</button></div>;
  }
  return <div className="page sb-create-page">
    <CreateAgentModal onClose={close} onCreated={(agent) => {
      pushToast(agent.purpose === 'education' ? 'Education agent created in draft for safe provisioning' : 'Agent created');
      navigate(`/agents/${agent.id}/instructions`, { replace: true });
    }} />
  </div>;
}
