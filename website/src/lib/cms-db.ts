import "server-only";
import { Pool } from "pg";
import { isPublishedPage, type PublishedPage } from "./cms";
import { collectPublicResources } from "./publication-policy";

let pool: Pool | undefined;
function getPool(): Pool | null {
  const connectionString = process.env.WEBSITE_CMS_DATABASE_URL;
  if (!connectionString) return null;
  if (!pool) pool = new Pool({ connectionString, max: 5, connectionTimeoutMillis: 3000, idleTimeoutMillis: 10000 });
  return pool;
}

/** A public-only query: the current published revision pointer is the sole source of truth.
 * Run with a database role that has SELECT only on the explicitly authorized views/tables. */
export async function loadPublishedPage(path: string, locale = "en"): Promise<PublishedPage | null> {
  const site = process.env.WEBSITE_CMS_SITE_SLUG;
  if (!site || !/^\/[a-z0-9/-]*$/.test(path) || !/^[a-z]{2}(?:-[A-Z]{2})?$/.test(locale)) return null;
  const db = getPool();
  if (!db) return null;
  const result = await db.query(
    `SELECT id, path, locale, revision, title, description, blocks
       FROM website_cms.public_published_pages
      WHERE site_slug = $1 AND path = $2 AND locale = $3
      LIMIT 1`,
    [site, path, locale],
  );
  const value: unknown = result.rows[0];
  return isPublishedPage(value) && value.path === path && value.locale === locale ? value : null;
}

/** Read-only publication index result.
 * Distinguish a healthy empty library from an unavailable data source. */
export type PublishedResourceSummary = {
  path: string;
  title: string;
  description: string;
};
export type PublishedResourceIndex =
  | { status: "ready"; resources: PublishedResourceSummary[] }
  | { status: "unavailable"; resources: [] };

export async function readPublishedResources(locale = "en"): Promise<PublishedResourceIndex> {
  const site = process.env.WEBSITE_CMS_SITE_SLUG;
  if (!site || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(site) ||
      !/^[a-z]{2}(?:-[A-Z]{2})?$/.test(locale)) return { status: "unavailable", resources: [] };
  const db = getPool();
  if (!db) return { status: "unavailable", resources: [] };
  try {
    // Only data exposed through the DBA-granted published-only security-barrier view.
    const result = await db.query<{
      id: string; path: string; locale: string; revision: number;
      title: string; description: string; blocks: unknown;
    }>(
      `SELECT id, path, locale, revision, title, description, blocks
         FROM website_cms.public_published_pages
        WHERE site_slug=$1 AND locale=$2 AND path LIKE '/content/%'
        ORDER BY path ASC LIMIT 100`,
      [site, locale],
    );
    // Never show a malformed or non-canonical page in a public listing.
    const resources = collectPublicResources(result.rows, locale);
    return { status: "ready", resources };
  } catch {
    // No raw SQL, schema or database detail is exposed publicly.
    return { status: "unavailable", resources: [] };
  }
}

/** Backwards-compatible list for sitemap generation. Never includes drafts. */
export async function loadPublishedResources(locale = "en"): Promise<PublishedResourceSummary[]> {
  return (await readPublishedResources(locale)).resources;
}
