import { NextResponse } from "next/server";
import { trashContentPage, restoreTrashedContentPage } from "../../../../../../lib/cms-editor";
import { parseManualPreservationIntent } from "../../../../../../lib/preservation-contract";
import { bodyJson, checkMutationRequest, ownerResponse, requireOwner } from "../../../../../../lib/owner-api";

export const dynamic = "force-dynamic";
type Params = { params: Promise<{pageId: string}> };

/** No purge action is intentionally provided. Only authenticated human requests. */
export async function POST(request: Request, {params}: Params) {
  const {pageId} = await params;
  // Check the feature gate before parsing any visitor-supplied preservation intent.
  if (process.env.BLOG_AUTO_DELETE_ENABLED !== "false")
    return ownerResponse({error:"Content preservation policy not configured"},503);
  const blocked = checkMutationRequest(request);
  if (blocked) return blocked;
  let input: ReturnType<typeof parseManualPreservationIntent>;
  try { input = parseManualPreservationIntent(await bodyJson(request)); }
  catch { return ownerResponse({error:"Invalid preservation request"},422); }
  if (!input) return ownerResponse({error:"Manual action and reason required"},422);
  const actor = await requireOwner(request, input.action === "trash" ? "cms:trash" : "cms:restore");
  if (actor instanceof NextResponse) return actor;
  try {
    const result = input.action === "trash"
      ? await trashContentPage(actor,pageId,input.reason)
      : await restoreTrashedContentPage(actor,pageId,input.reason);
    return ownerResponse({...result, visibility:"pending-public-cache-reconciliation"},202);
  } catch {
    return ownerResponse({error:"Content lifecycle action denied or unavailable"},409);
  }
}
