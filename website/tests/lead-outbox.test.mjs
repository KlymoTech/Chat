import { createHmac } from "node:crypto";
import { describe, expect, it } from "vitest";
import { approvedCrmUrl, retryDelaySeconds, signedLeadEnvelope } from "../scripts/lead-worker-contract.mjs";

describe("signed lead delivery contract", () => {
  it("allows only a server-approved HTTPS destination",()=>{
    expect(approvedCrmUrl("https://crm.business.tld/hooks/accepted")).toBe("https://crm.business.tld/hooks/accepted");
    for (const value of [
      "http://crm.business.tld/hook","https://127.0.0.1/path",
      "https://localhost/hook","https://10.0.0.1/",
      "https://crm.business.tld:8080/hook",
      "https://user:pass@crm.business.tld/hook",
      "https://crm.business.tld/hook?secret=123",
      "https://example.com/hook",
      "file:///tmp/secret",
    ]) expect(approvedCrmUrl(value)).toBeNull();
  });
  it("uses bounded retry intervals and never silently discards failed records",()=>{
    expect(retryDelaySeconds(1)).toBe(30);
    expect(retryDelaySeconds(2)).toBe(60);
    expect(retryDelaySeconds(20)).toBe(86400);
    expect(()=>retryDelaySeconds(-1)).toThrow();
  });
  it("signs exactly the HTTP payload and includes one stable event identifier",()=>{
    const eventId="550e8400-e29b-41d4-a716-446655440000";
    const leadId="62a2a2bf-1b2a-4fe2-a333-12b2a2a2a2a2";
    const secret="k".repeat(40);
    const bundle=signedLeadEnvelope(eventId,leadId,{
      full_name:"Visitor",email:"visitor@testmail.tld",message:"Please contact me",
    },secret,1700000000000);
    expect(bundle.headers["X-Website-Event-Id"]).toBe(eventId);
    expect(bundle.headers["X-Website-Timestamp"]).toBe("1700000000");
    expect(JSON.parse(bundle.body)).toMatchObject({
      schema:"website.lead.accepted.v1",eventId,leadId,purpose:"respond-to-enquiry",
    });
    const expected=createHmac("sha256",secret).update("1700000000."+bundle.body).digest("hex");
    expect(bundle.headers["X-Website-Signature"]).toBe("sha256="+expected);
    expect(bundle.body).not.toContain(secret);
  });
});
