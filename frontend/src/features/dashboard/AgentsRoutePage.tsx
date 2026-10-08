import { useNavigate, useSearchParams } from 'react-router-dom';
import { useToast } from '@/components/providers';
import { AgentsPage, CreateAgentModal } from '@/pages/AgentsPage';

/** Deep-link into the existing creation workflow without copying business logic. */
export function AgentsRoutePage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const { pushToast } = useToast();
  if (params.get('create') !== '1') return <AgentsPage />;
  const close = () => {
    const next = new URLSearchParams(params);
    next.delete('create');
    setParams(next, { replace: true });
  };
  return <div className="page sb-create-page">
    <CreateAgentModal onClose={close} onCreated={(agent) => {
      pushToast(agent.purpose === 'education' ? 'Education agent created in draft for safe provisioning' : 'Agent created');
      navigate(`/agents/${agent.id}/instructions`, { replace: true });
    }} />
  </div>;
}
