/** A future analytics adapter must gate every optional request on the latest consent.
 * This module does not enable analytics, set cookies, transmit events or perform network I/O.
 * Keep essential functionality independent from this choice.
 */
export type Purpose = "analytics" | "marketing";
export type Permission = Record<Purpose, boolean>;
export const DENY_ALL: Readonly<Permission> = Object.freeze({ analytics: false, marketing: false });
export function maySendOptionalEvent(purpose: Purpose, current: Permission): boolean {
  return current[purpose] === true;
}
