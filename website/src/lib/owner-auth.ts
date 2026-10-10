import "server-only";
import { createRemoteJWKSet, jwtVerify } from "jose";
import type { CmsActor } from "./cms-editor";
import { actorFromVerifiedClaims } from "./owner-claims";
import { trustedOwnerJwksEndpoint } from "./owner-endpoint-policy";
import { ownerMfaSatisfied } from "./owner-mfa-policy";
import { readOwnerCookie, sessionCookie } from "./owner-session";

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
  // Bearer takes precedence: an invalid supplied token must never fall back to cookies.
  const session = bearer ? null : await readOwnerCookie(request,sessionCookie,"owner-session");
  const token = bearer?.startsWith("Bearer ") ? bearer.slice(7) : (session?.accessToken ?? "");
  if (typeof token !== "string" || token.length > 8192 ||
      !/^[\w.-]+$/.test(token) || token.split(".").length !== 3) return null;
  try {
    if (!trustedOwnerJwksEndpoint(issuer,jwksUrl)) return null;
    const keyUrl=new URL(jwksUrl);
    if (!jwks || jwksUrlCached !== jwksUrl) {
      jwks = createRemoteJWKSet(keyUrl, { timeoutDuration: 3000, cooldownDuration: 30000 });
      jwksUrlCached = jwksUrl;
    }
    const { payload } = await jwtVerify(token, jwks, {
      issuer, audience, algorithms: ["RS256"], clockTolerance: "5s", maxTokenAge: "15m",
    });
    if(!ownerMfaSatisfied(payload,{
      required:process.env.WEBSITE_CMS_REQUIRE_MFA==="true",
      acceptedAcr:process.env.WEBSITE_CMS_MFA_ACCEPTED_ACR||undefined,
      maxAgeSeconds:43200,
    }))return null;
    return actorFromVerifiedClaims(payload, process.env.WEBSITE_CMS_OWNER_SITE_ID);
  } catch {
    return null;
  }
}
