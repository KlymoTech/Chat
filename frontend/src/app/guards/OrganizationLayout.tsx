import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '@/components/providers';

/** Guards account-level organization routes and remounts them per session. */
export function OrganizationLayout() {
  const { session } = useAuth();
  const location = useLocation();
  if (!session) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (session.user.emailVerified === false) return <Navigate to="/verify-email" replace />;
  return <Outlet key={session.accessToken} />;
}
