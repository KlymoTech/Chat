import { hasNavigationPermission, type NavigationScope } from '@/lib/materialm-navigation';

/** Explicit workspace permissions take precedence over organization-level roles.
 * This only controls the UI; the server still authorizes every API request.
 */
export function canUseDashboardCapability(scope: NavigationScope, permission: string): boolean {
  if (scope.permissions) return scope.permissions.includes('*') || scope.permissions.includes(permission);
  return hasNavigationPermission(scope, permission);
}
