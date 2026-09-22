/** @deprecated Use the explicitly named super-admin feature boundary. */
export { PlatformAdminPage } from '@/features/super-admin/PlatformAdminPage';
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
