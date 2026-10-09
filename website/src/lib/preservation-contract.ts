/** Source-content preservation is manual-only. No automatic expiration or purge. */
export type ManualPreservationIntent = Readonly<{action:"trash"|"restore";reason:string}>;
export function parseManualPreservationIntent(value:unknown):ManualPreservationIntent|null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const input=value as Record<string,unknown>;
  if ((input.action!=="trash" && input.action!=="restore") || typeof input.reason!=="string") return null;
  const reason=input.reason.trim();
  if (reason.length<10 || reason.length>500) return null;
  return {action:input.action,reason};
}
export function assertManualPreservationOnly(flag:string|undefined):void {
  if(flag!=="false") throw new Error("Manual-only source preservation is not confirmed");
}
