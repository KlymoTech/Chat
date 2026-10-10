import { NextRequest, NextResponse } from "next/server";
import { loadPublishedPage } from "../../../../lib/cms-db";
export const dynamic = "force-dynamic";
export async function GET(request: NextRequest) {
  const path = request.nextUrl.searchParams.get("path") ?? "";
  const locale = request.nextUrl.searchParams.get("locale") ?? "en";
  if (path.length > 512 || !/^\/[a-z0-9/-]*$/.test(path) || !/^[a-z]{2}(?:-[A-Z]{2})?$/.test(locale)) {
    return NextResponse.json({ error: "Invalid page lookup" }, { status: 400, headers: { "Cache-Control": "no-store" } });
  }
  try {
    const page = await loadPublishedPage(path, locale);
    if (!page) return NextResponse.json({ error: "Not found" }, { status: 404, headers: { "Cache-Control": "no-store" } });
    return NextResponse.json(page, { headers: { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" } });
  } catch {
    return NextResponse.json({ error: "Content temporarily unavailable" }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
