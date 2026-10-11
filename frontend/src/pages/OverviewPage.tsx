import { useWorkspace } from '@/components/providers';
import { WorkspaceConfiguredDashboard } from '@/features/dashboard/WorkspaceConfiguredDashboard';
import { SaasBotOverview } from '@/features/dashboard/SaasBotOverview';
import { useWorkspaceBrandRuntime } from '@/features/branding/WorkspaceBrandRuntime';

export function OverviewPage() {
  const brand = useWorkspaceBrandRuntime();
  const { activeWorkspace } = useWorkspace();
  if (brand?.identity.brandedDashboard && brand.dashboard.widgets.length > 0) {
    return <WorkspaceConfiguredDashboard brand={brand} />;
  }
  // Never reuse a previous workspace's in-flight dashboard data or filters.
  return <SaasBotOverview key={activeWorkspace?.id ?? 'workspace-loading'} />;
}
