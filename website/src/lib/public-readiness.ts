import "server-only";
import { Pool } from "pg";

/** A public-CMS dependency probe, never a production launch approval gate. */
export type PublicReadinessResult = "ready" | "unavailable";

export function publicReadinessConfigured(input: {
  enabled?: string; siteSlug?: string; readerUrl?: string;
}): boolean {
  if (input.enabled !== "true" ||
      typeof input.siteSlug !== "string" ||
      !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(input.siteSlug) ||
      typeof input.readerUrl !== "string") return false;

  try {
    const url = new URL(input.readerUrl);
    return (url.protocol === "postgres:" || url.protocol === "postgresql:") &&
      Boolean(url.hostname) && Boolean(url.pathname && url.pathname !== "/");
  } catch {
    return false;
  }
}

let reader: Pool | undefined;
export async function checkPublicCmsReadiness(): Promise<PublicReadinessResult> {
  if (!publicReadinessConfigured({
    enabled: process.env.WEBSITE_RUNTIME_READINESS_ENABLED,
    siteSlug: process.env.WEBSITE_CMS_SITE_SLUG,
    readerUrl: process.env.WEBSITE_CMS_DATABASE_URL,
  })) return "unavailable";

  try {
    if (!reader) reader = new Pool({
      connectionString: process.env.WEBSITE_CMS_DATABASE_URL,
      max: 2,
      connectionTimeoutMillis: 1500,
      query_timeout: 2500,
      idleTimeoutMillis: 10000,
    });
    // Verify the intended least-privilege public read view is present and
    // accessible. No rows, page content, or private DB details are returned.
    await reader.query("SELECT 1 FROM website_cms.public_published_pages LIMIT 0");
    return "ready";
  } catch {
    return "unavailable";
  }
}
