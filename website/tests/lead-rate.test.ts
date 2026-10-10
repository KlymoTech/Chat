import { describe, expect, it } from "vitest";
import { LEAD_RATE_LIMITS, LeadRateNotConfigured, leadRateSubject } from "../src/lib/lead-rate";

const site="550e8400-e29b-41d4-a716-446655440000";
const secret="shared-secret-with-adequate-entropy".repeat(2);

describe("privacy-preserving admission counters",()=>{
  it("has bounded conservative hourly budgets",()=>{
    expect(LEAD_RATE_LIMITS.contactPerHour).toBe(3);
    expect(LEAD_RATE_LIMITS.sitePerHour).toBe(100);
  });
  it("derives stable deterministic opaque contact buckets",()=>{
    const key=leadRateSubject("contact",site," Test@Example.org ",secret);
    expect(key).toMatch(/^[0-9a-f]{64}$/);
    expect(key).toBe(leadRateSubject("contact",site,"test@example.org",secret));
    expect(key).not.toContain("test@example.org");
    expect(key).not.toBe(leadRateSubject("contact",site,"other@example.org",secret));
    expect(key).not.toBe(leadRateSubject("site",site,"test@example.org",secret));
  });
  it("keeps sites and purpose dimensions isolated",()=>{
    const otherSite="62a2a2bf-1b2a-4fe2-a333-12b2a2a2a2a2";
    expect(leadRateSubject("contact",site,"test@example.org",secret))
      .not.toBe(leadRateSubject("contact",otherSite,"test@example.org",secret));
    expect(leadRateSubject("site",site,"one@example.org",secret))
      .toBe(leadRateSubject("site",site,"two@example.org",secret));
  });
  it("fails closed without secret or with invalid dimensions",()=>{
    expect(()=>leadRateSubject("contact",site,"name@example.org",undefined)).toThrow(LeadRateNotConfigured);
    expect(()=>leadRateSubject("site",site,"", "short")).toThrow(LeadRateNotConfigured);
    expect(()=>leadRateSubject("contact","not-uuid","name@example.org",secret)).toThrow(LeadRateNotConfigured);
    expect(()=>leadRateSubject("other" as "site",site,"name@example.org",secret)).toThrow(LeadRateNotConfigured);
  });
});
