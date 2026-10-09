import { NextResponse } from "next/server";
import { approveDraft, publishApproved, restorePublished, saveDraft } from "../../../../../../lib/cms-editor";
import { bodyJson, checkMutationRequest, draftFromUnknown, ownerResponse, requireOwner } from "../../../../../../lib/owner-api";

export const dynamic = "force-dynamic";
type Params = { params: Promise<{ pageId: string; action: string }> };
export async function POST(request: Request, { params }: Params) {
  const { pageId, action } = await params;
  const needed = action === "draft" ? "cms:draft" : action === "approve" ? "cms:review" :
    action === "publish" || action === "restore" ? "cms:publish" : null;
  if (!needed) return ownerResponse({ error: "Unknown CMS action" }, 404);
  const actor = await requireOwner(request, needed);
  if (actor instanceof NextResponse) return actor;
  const invalid = checkMutationRequest(request);
  if (invalid) return invalid;
  try {
    const body = await bodyJson(request);
    if (action === "draft") {
      const doc = draftFromUnknown(body);
      if (!doc) return ownerResponse({ error: "Invalid document" }, 422);
      const revisionId = await saveDraft(actor, pageId, doc);
      return ownerResponse({ revisionId, state: "draft" }, 201);
    }
    if (!body || typeof body !== "object" || Array.isArray(body)) return ownerResponse({ error: "Invalid action" }, 422);
    const input = body as Record<string, unknown>;
    if (typeof input.revisionId !== "string") return ownerResponse({ error: "Revision ID required" }, 422);
    if (action === "approve") {
      const approvalId = await approveDraft(actor, pageId, input.revisionId);
      return ownerResponse({ approvalId, state: "approved" });
    }
    if (action === "publish") {
      const revisionId = await publishApproved(actor, pageId, input.revisionId);
      return ownerResponse({ revisionId, state: "publication-queued" }, 202);
    }
    const revisionId = await restorePublished(actor, pageId, input.revisionId);
    return ownerResponse({ revisionId, sourceRevisionId: input.revisionId,
      state: "restoration-queued" }, 202);
  } catch {
    return ownerResponse({ error: "CMS action failed, state unchanged or rolled back" }, 409);
  }
}
