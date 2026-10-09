import "server-only";
import { randomUUID } from "node:crypto";
import { Pool } from "pg";
import type { LeadInput } from "./lead-input";

let pool: Pool | undefined;
function getPool() {
  const connectionString = process.env.WEBSITE_LEADS_DATABASE_URL;
  if (!connectionString) return null;
  if (!pool) pool = new Pool({ connectionString, max: 5, connectionTimeoutMillis: 3000 });
  return pool;
}
export async function saveLead(input: LeadInput): Promise<{ id: string; accepted: true } | null> {
  const slug = process.env.WEBSITE_CMS_SITE_SLUG;
  const db = getPool();
  if (!slug || !db) return null;
  const client = await db.connect();
  try {
    await client.query("BEGIN");
    const site = await client.query<{id: string}>("SELECT id FROM website_cms.sites WHERE slug = $1", [slug]);
    if (site.rowCount !== 1) throw new Error("Site not provisioned");
    const siteId = site.rows[0].id;
    const leadId = randomUUID();
    const inserted = await client.query<{id: string}>(
      `INSERT INTO website_cms.lead_submissions
      (id, site_id, idempotency_key, full_name, email, message, privacy_acknowledged)
      VALUES ($1,$2,$3,$4,$5,$6,TRUE)
      ON CONFLICT (site_id, idempotency_key) DO NOTHING RETURNING id`,
      [leadId, siteId, input.idempotencyKey, input.fullName, input.email, input.message],
    );
    const id = inserted.rows[0]?.id ??
      (await client.query<{id: string}>(
        "SELECT id FROM website_cms.lead_submissions WHERE site_id=$1 AND idempotency_key=$2",
        [siteId, input.idempotencyKey]
      )).rows[0]?.id;
    if (!id) throw new Error("Submission could not be persisted");
    if (inserted.rowCount === 1) {
      await client.query(
        `INSERT INTO website_cms.outbox (id, site_id, event_type, payload)
         VALUES ($1,$2,'lead.accepted',jsonb_build_object('leadId',$3::text))`,
        [randomUUID(), siteId, id],
      );
    }
    await client.query("COMMIT");
    return { id, accepted: true };
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}
