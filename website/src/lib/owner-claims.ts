import type { CmsActor } from "./cms-editor";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const permissions = ["cms:read", "cms:draft", "cms:review", "cms:publish", "cms:trash", "cms:restore", "cms:media", "cms:media:review", "cms:media:publish", "cms:automation", "cms:privacy", "cms:redirect"] as const;
type CmsPermission = typeof permissions[number];

/** Only pass cryptographically VERIFIED JWT claims to this validator. */
export function actorFromVerifiedClaims(claims: Record<string, unknown>, expectedSite: string | undefined): CmsActor | null {
  const siteId = claims.site_id;
  const raw = claims.permissions;
  if (typeof claims.sub !== "string" || !uuid.test(claims.sub) ||
      typeof siteId !== "string" || !uuid.test(siteId) ||
      !expectedSite || !uuid.test(expectedSite) || siteId !== expectedSite ||
      !Array.isArray(raw) || raw.length > permissions.length ||
      raw.some(value => typeof value !== "string" || !permissions.includes(value as CmsPermission))) return null;
  return { id: claims.sub, siteId, permissions: [...new Set(raw)] as CmsPermission[] };
}
