import { createHmac } from "node:crypto";

/** Refuse accidental exfiltration to loopback, private IPs, or unapproved schemes. */
export function approvedCrmUrl(raw) {
  if (typeof raw !== "string") return null;
  try {
    const url = new URL(raw);
    if (url.protocol !== "https:" || url.username || url.password ||
        url.hash || url.search || url.port || url.pathname.length > 1024) return null;
    const host = url.hostname.toLowerCase().replace(/\.$/,"");
    if (!host.includes(".") || host === "localhost" ||
        host.endsWith(".localhost") || host.endsWith(".local") ||
        host.endsWith(".internal") || host.endsWith(".test") ||
        host.endsWith(".example") || host === "example.com" ||
        host.endsWith(".example.com") || host.startsWith("[") ||
        /^\d+(?:\.\d+){3}$/.test(host)) return null;
    if (!/^[a-z0-9.-]+$/.test(host)) return null;
    return url.toString();
  } catch { return null; }
}

/** Backoff is bounded but messages are never discarded after repeated failures. */
export function retryDelaySeconds(attempt) {
  if (!Number.isSafeInteger(attempt) || attempt < 1) throw new Error("Invalid attempt");
  return Math.min(24*60*60,30*2**Math.min(12,attempt-1));
}
export function signedLeadEnvelope(eventId, leadId, lead, secret, now=Date.now()) {
  if (!/^[0-9a-f-]{36}$/i.test(eventId) || !/^[0-9a-f-]{36}$/i.test(leadId) ||
      typeof secret !== "string" || secret.length < 32) throw new Error("Invalid delivery configuration");
  const timestamp=Math.floor(now/1000).toString();
  const body=JSON.stringify({
    schema:"website.lead.accepted.v1",eventId,leadId,
    contact:{fullName:lead.full_name,email:lead.email},
    enquiry:{message:lead.message},
    purpose:"respond-to-enquiry",
  });
  const signature=createHmac("sha256",secret).update(timestamp+"."+body).digest("hex");
  return {body,headers:{
    "Content-Type":"application/json",
    "X-Website-Event-Id":eventId,
    "X-Website-Timestamp":timestamp,
    "X-Website-Signature":"sha256="+signature,
  }};
}
