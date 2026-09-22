import { Navigate, useLocation } from 'react-router-dom';
import { MaterialmAppShell } from '@/components/materialm/MaterialmAppShell';
import { useAuth } from '@/components/providers';
import { WorkspaceSetupGate } from '@/components/WorkspaceSetup';

/** Guards workspace routes and applies the workspace setup gate. */
export function ProtectedLayout() {
  const { session } = useAuth();
  const location = useLocation();
  if (!session) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (session.user.emailVerified === false) return <Navigate to="/verify-email" replace />;
  return <WorkspaceSetupGate><MaterialmAppShell /></WorkspaceSetupGate>;
}
