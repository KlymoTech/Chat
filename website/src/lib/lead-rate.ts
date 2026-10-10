import { createHmac } from "node:crypto";

/** Fixed conservative backstop. The public form remains disabled until verified. */
export const LEAD_RATE_LIMITS = Object.freeze({
  contactPerHour: 3,
  sitePerHour: 100,
});

export type RateDimension = "site" | "contact";
export class LeadRateLimited extends Error {
  constructor() { super("Enquiry capacity temporarily reached"); this.name = "LeadRateLimited"; }
}
export class LeadRateNotConfigured extends Error {
  constructor() { super("Lead abuse protection not configured"); this.name = "LeadRateNotConfigured"; }
}

/**
 * No IP or raw email is retained in counters. HMAC prevents reversing
 * ordinary email addresses with a dictionary attack on an unkeyed hash.
 */
export function leadRateSubject(
  dimension: RateDimension, siteId: string, email: string, secret: string | undefined,
): string {
  if (!secret || secret.length < 32) throw new LeadRateNotConfigured();
  if (!/^[0-9a-f-]{36}$/i.test(siteId)) throw new LeadRateNotConfigured();
  if (dimension !== "site" && dimension !== "contact") throw new LeadRateNotConfigured();
  const subject = dimension === "site" ? "total" : email.trim().toLowerCase();
  return createHmac("sha256",secret).update([dimension,siteId,subject].join("\n")).digest("hex");
}
