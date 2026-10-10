import { NextResponse } from "next/server";
import { createPage, listOwnerPages } from "../../../../lib/cms-editor";
import { bodyJson, checkMutationRequest, draftFromUnknown, ownerResponse, requireOwner } from "../../../../lib/owner-api";

export const dynamic = "force-dynamic";
/** Server-side owner operations. Never return drafts to public pages. */
export async function GET(request: Request) {
  const actor = await requireOwner(request, "cms:read");
  if (actor instanceof NextResponse) return actor;
  try {
    return ownerResponse({ pages: await listOwnerPages(actor),actorId:actor.id,siteId:actor.siteId });
  } catch {
    return ownerResponse({ error: "Unable to list pages" }, 503);
  }
}
export async function POST(request: Request) {
  const actor = await requireOwner(request, "cms:draft");
  if (actor instanceof NextResponse) return actor;
  const invalid = checkMutationRequest(request);
  if (invalid) return invalid;
  try {
    const raw = await bodyJson(request);
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return ownerResponse({ error: "Invalid page" }, 422);
    const obj = raw as Record<string, unknown>;
    const document = draftFromUnknown(obj.document);
    if (!document || typeof obj.path !== "string" || typeof obj.locale !== "string") return ownerResponse({ error: "Invalid page" }, 422);
    const receipt = await createPage(actor, obj.path, obj.locale, document);
    return ownerResponse(receipt, 201);
  } catch {
    return ownerResponse({ error: "Page could not be created; check route uniqueness and database availability" }, 409);
  }
}
