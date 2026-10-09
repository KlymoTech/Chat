import "server-only";
import { Pool } from "pg";
import { isPublishedPage, type PublishedPage } from "./cms";

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
  return isPublishedPage(value) ? value : null;
}

/** Published-only resource listing; never queries drafts or admin credentials. */
export async function loadPublishedResources(locale = "en"): Promise<Array<{
  path: string; title: string; description: string;
}>> {
  const site = process.env.WEBSITE_CMS_SITE_SLUG;
  if (!site || !/^[a-z]{2}(?:-[A-Z]{2})?$/.test(locale)) return [];
  const db = getPool();
  if (!db) return [];
  try {
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
    return result.rows.filter(page => isPublishedPage(page))
      .map(page => ({ path: page.path, title: page.title, description: page.description }));
  } catch {
    return [];
  }
}
