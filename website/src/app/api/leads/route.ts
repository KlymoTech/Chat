import { NextRequest, NextResponse } from "next/server";
import { parseLeadInput } from "../../../lib/lead-input";
import { saveLead } from "../../../lib/leads-db";
export const dynamic = "force-dynamic";
const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
export async function POST(request: NextRequest) {
  // Feature fails closed until spam control, policy, and database privileges are approved.
  if (process.env.WEBSITE_LEAD_CAPTURE_ENABLED !== "true" || !process.env.WEBSITE_LEADS_DATABASE_URL)
    return NextResponse.json({ error: "Enquiries are not available online yet" }, { status: 503, headers });
  const origin = request.headers.get("origin");
  const expected = process.env.WEBSITE_CANONICAL_ORIGIN;
  if (!origin || !expected || origin !== expected)
    return NextResponse.json({ error: "Origin not allowed" }, { status: 403, headers });
  if (!(request.headers.get("content-type") ?? "").startsWith("application/json"))
    return NextResponse.json({ error: "JSON required" }, { status: 415, headers });
  const limit = Number(request.headers.get("content-length") ?? 0);
  if (limit > 8192) return NextResponse.json({ error: "Request too large" }, { status: 413, headers });
  try {
    const raw = await request.text();
    if (raw.length > 8192) return NextResponse.json({ error: "Request too large" }, { status: 413, headers });
    const parsed = parseLeadInput(JSON.parse(raw));
    if (!parsed) return NextResponse.json({ error: "Invalid enquiry" }, { status: 422, headers });
    const result = await saveLead(parsed);
    if (!result) throw new Error("Unconfigured storage");
    return NextResponse.json(result, { status: 201, headers });
  } catch {
    return NextResponse.json({ error: "Enquiry could not be saved. Please retry or use our contact email." }, { status: 503, headers });
  }
}
