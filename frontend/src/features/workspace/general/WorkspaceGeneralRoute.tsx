import { Navigate, useLocation, useSearchParams } from 'react-router-dom';
import { WorkspacePage } from '@/pages/WorkspacePage';

/**
 * Expose the canonical General Settings URL without moving or deleting the
 * existing Workspace page. Other tabs continue to use their original URL until
 * each is implemented and verified as an independent settings feature.
 */
export function WorkspaceGeneralRoute() {
  const location = useLocation();
  const [params] = useSearchParams();
  const section = params.get('section');
  if (section && section !== 'workspace') {
    return <Navigate to={{ pathname: '/workspace', search: location.search }} replace />;
  }
  return <WorkspacePage />;
}
