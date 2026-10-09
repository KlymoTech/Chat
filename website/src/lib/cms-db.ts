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
