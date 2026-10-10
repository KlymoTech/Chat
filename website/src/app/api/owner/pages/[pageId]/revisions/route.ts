import { NextResponse } from "next/server";
import { listOwnerRevisions } from "../../../../../../lib/cms-editor";
import { ownerResponse, requireOwner } from "../../../../../../lib/owner-api";

export const dynamic = "force-dynamic";
type Params = { params: Promise<{ pageId: string }> };
export async function GET(request: Request, { params }: Params) {
  const actor = await requireOwner(request, "cms:read");
  if (actor instanceof NextResponse) return actor;
  const { pageId } = await params;
  try {
    return ownerResponse({ revisions: await listOwnerRevisions(actor, pageId) });
  } catch {
    return ownerResponse({ error: "Revision history unavailable" }, 404);
  }
}
