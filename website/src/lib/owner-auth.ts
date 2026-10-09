import "server-only";
import { createRemoteJWKSet, jwtVerify } from "jose";
import type { CmsActor } from "./cms-editor";
import { actorFromVerifiedClaims } from "./owner-claims";

let jwks: ReturnType<typeof createRemoteJWKSet> | undefined;
let jwksUrlCached: string | undefined;

/**
 * Authorization uses RS256 access tokens from a configured external identity provider.
 * No actor/role/site identity is ever accepted from request JSON or unsigned headers.
 * Rejects missing config, unknown issuer/audience, expired tokens and cross-site tokens.
 */
export async function authenticateOwner(request: Request): Promise<CmsActor | null> {
  if (process.env.WEBSITE_CMS_OWNER_API_ENABLED !== "true" ||
      process.env.WEBSITE_CMS_OWNER_DB_RLS_VERIFIED !== "true") return null;
  const issuer = process.env.WEBSITE_CMS_OIDC_ISSUER;
  const audience = process.env.WEBSITE_CMS_OIDC_AUDIENCE;
  const jwksUrl = process.env.WEBSITE_CMS_OIDC_JWKS_URL;
  if (!issuer || !audience || !jwksUrl) return null;
  const bearer = request.headers.get("authorization");
  if (!bearer?.startsWith("Bearer ")) return null;
  const token = bearer.slice(7);
  if (token.length > 8192 || !/^[\w.-]+$/.test(token) || token.split(".").length !== 3) return null;
  try {
    const issuerUrl = new URL(issuer), keyUrl = new URL(jwksUrl);
    if (issuerUrl.protocol !== "https:" || keyUrl.protocol !== "https:" ||
        issuerUrl.username || issuerUrl.password || keyUrl.username || keyUrl.password ||
        keyUrl.hash || keyUrl.search || issuerUrl.hash || issuerUrl.search) return null;
    if (!jwks || jwksUrlCached !== jwksUrl) {
      jwks = createRemoteJWKSet(keyUrl, { timeoutDuration: 3000, cooldownDuration: 30000 });
      jwksUrlCached = jwksUrl;
    }
    const { payload } = await jwtVerify(token, jwks, {
      issuer, audience, algorithms: ["RS256"], clockTolerance: "5s", maxTokenAge: "15m",
    });
    return actorFromVerifiedClaims(payload, process.env.WEBSITE_CMS_OWNER_SITE_ID);
  } catch {
    return null;
  }
}
