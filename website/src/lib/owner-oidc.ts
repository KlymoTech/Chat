import "server-only";

export type OwnerOidcConfig = Readonly<{
  origin: string; issuer: string; audience: string; clientId: string;
  authorizationEndpoint: string; tokenEndpoint: string; callback: string;
}>;

/** Fail-closed: all OAuth destinations are operator configured, HTTPS, and on the issuer origin. */
export function ownerOidcConfig(): OwnerOidcConfig | null {
  if (process.env.WEBSITE_CMS_OWNER_API_ENABLED !== "true" ||
      process.env.WEBSITE_CMS_OWNER_DB_RLS_VERIFIED !== "true") return null;
  const values = [
    process.env.WEBSITE_CANONICAL_ORIGIN, process.env.WEBSITE_CMS_OIDC_ISSUER,
    process.env.WEBSITE_CMS_OIDC_AUDIENCE, process.env.WEBSITE_CMS_OIDC_CLIENT_ID,
    process.env.WEBSITE_CMS_OIDC_AUTHORIZATION_ENDPOINT,
    process.env.WEBSITE_CMS_OIDC_TOKEN_ENDPOINT,
  ];
  if (values.some(v => !v)) return null;
  try {
    const [origin, issuer, audience, clientId, authorizationEndpoint, tokenEndpoint] = values as string[];
    const site = new URL(origin), iss = new URL(issuer), auth = new URL(authorizationEndpoint), token = new URL(tokenEndpoint);
    if ([site,iss,auth,token].some(u => u.protocol !== "https:" || u.username || u.password ||
      u.search || u.hash) || site.pathname !== "/" || iss.origin !== auth.origin ||
      iss.origin !== token.origin || !audience.trim() || !clientId.trim() ||
      clientId.length > 256 || issuer.length > 2048) return null;
    return {origin:site.origin,issuer,audience,clientId,authorizationEndpoint,tokenEndpoint,
      callback:new URL("/api/owner/auth/callback",site).toString()};
  } catch { return null; }
}
