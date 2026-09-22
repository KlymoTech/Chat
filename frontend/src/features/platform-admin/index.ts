/** @deprecated Use the explicitly named super-admin feature boundary. */
export { SuperAdminPage as PlatformAdminPage } from '@/features/super-admin/SuperAdminPage';
export { platformAdminApi } from '@/lib/platform-admin-api';
export type {
  PlatformOverview,
  PlatformTenantDetail,
  PlatformTenantSummary,
  PlatformTenantUser,
  PlatformEntitlement,
  PlatformConfiguration,
  PlatformAdminPermissions,
  PlatformOperator,
} from '@/lib/platform-admin-api';
