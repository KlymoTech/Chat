export type CmsInvalidation = Readonly<{
  eventId: string;
  pageId: string;
  eventType: "cms.published" | "cms.restored" | "cms.trashed" | "cms.restored_from_trash";
  path: string;
}>;
export const CMS_EVENTS: readonly CmsInvalidation["eventType"][];
export function parseCmsInvalidation(value: unknown): CmsInvalidation | null;
export function signCmsInvalidation(
  value: unknown, secret: string, at?: number,
): {body:string;headers:Record<string,string>};
export function verifyCmsInvalidation(
  raw: string, headers: Headers, secret: string, now?: number,
): CmsInvalidation | null;
export function verifiedCmsOrigin(raw:unknown):string|null;
export function cmsRetryDelaySeconds(attempt:number):number;
