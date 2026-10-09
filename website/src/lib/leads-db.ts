import "server-only";
import { randomUUID, createHash } from "node:crypto";
import { Pool } from "pg";
import type { LeadInput } from "./lead-input";
import { leadRateSubject, LEAD_RATE_LIMITS, LeadRateLimited, LeadRateNotConfigured } from "./lead-rate";

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
  const fingerprint = createHash("sha256").update([input.fullName, input.email, input.message, "true"].join("\n")).digest("hex");
  // Fail closed before opening a transaction if abuse controls are not configured.
  if (process.env.WEBSITE_LEAD_RATE_ENABLED !== "true") throw new LeadRateNotConfigured();
  const rateSecret = process.env.WEBSITE_LEAD_RATE_SECRET;
  if (!rateSecret || rateSecret.length < 32) throw new LeadRateNotConfigured();
  const client = await db.connect();
  try {
    await client.query("BEGIN");
    const site = await client.query<{id: string}>("SELECT id FROM website_cms.sites WHERE slug = $1", [slug]);
    if (site.rowCount !== 1) throw new Error("Site not provisioned");
    const siteId = site.rows[0].id;
    const leadId = randomUUID();
    const inserted = await client.query<{id: string; payload_sha256: string}>(
      `INSERT INTO website_cms.lead_submissions
      (id, site_id, idempotency_key, full_name, email, message, privacy_acknowledged, payload_sha256)
      VALUES ($1,$2,$3,$4,$5,$6,TRUE,$7)
      ON CONFLICT (site_id, idempotency_key) DO NOTHING RETURNING id, payload_sha256`,
      [leadId, siteId, input.idempotencyKey, input.fullName, input.email, input.message, fingerprint],
    );
    const existing = inserted.rows[0] ??
      (await client.query<{id: string; payload_sha256: string}>(
        "SELECT id, payload_sha256 FROM website_cms.lead_submissions WHERE site_id=$1 AND idempotency_key=$2 FOR UPDATE",
        [siteId, input.idempotencyKey]
      )).rows[0];
    if (!existing?.id) throw new Error("Submission could not be persisted");
    if (existing.payload_sha256 !== fingerprint) throw new LeadIdempotencyConflict();
    const id = existing.id;
    if (inserted.rowCount === 1) {
      // Charge quotas only for a NEW durable lead. Idempotent retries remain free.
      // Fixed lock order (site then contact) prevents multi-bucket deadlocks.
      for (const [dimension, maximum] of [
        ["site", LEAD_RATE_LIMITS.sitePerHour],
        ["contact", LEAD_RATE_LIMITS.contactPerHour],
      ] as const) {
        const key = leadRateSubject(dimension, siteId, input.email, rateSecret);
        const counted = await client.query(
          `INSERT INTO website_cms.lead_rate_windows
           (site_id,window_start,dimension,subject_hash,accepted_count)
           VALUES ($1,date_trunc('hour',now()),$2,$3,1)
           ON CONFLICT(site_id,window_start,dimension,subject_hash)
           DO UPDATE SET accepted_count=website_cms.lead_rate_windows.accepted_count+1
           WHERE website_cms.lead_rate_windows.accepted_count < $4
           RETURNING accepted_count`,
          [siteId, dimension, key, maximum],
        );
        if (counted.rowCount !== 1) throw new LeadRateLimited();
      }
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

export class LeadIdempotencyConflict extends Error {
  constructor() { super("Idempotency key reused with different payload"); this.name = "LeadIdempotencyConflict"; }
}
