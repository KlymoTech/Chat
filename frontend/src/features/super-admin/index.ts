/** Global super-admin control-plane feature boundary. */
export { SuperAdminPage } from './SuperAdminPage';
/** @deprecated Use SuperAdminPage. */
export { SuperAdminPage as PlatformAdminPage } from './SuperAdminPage';
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
