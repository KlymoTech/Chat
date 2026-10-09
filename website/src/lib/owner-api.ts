import { NextResponse } from "next/server";
import { authenticateOwner } from "./owner-auth";
import type { CmsActor, DraftDocument } from "./cms-editor";
import {validBuilderIdentities,validBuilderSection} from "./builder-contract";

export const privateHeaders = { "Cache-Control": "no-store, private", "X-Content-Type-Options": "nosniff" };
export function ownerResponse(value: unknown, status = 200): NextResponse {
  return NextResponse.json(value, { status, headers: privateHeaders });
}
export async function requireOwner(request: Request, permission: CmsActor["permissions"][number]): Promise<CmsActor | NextResponse> {
  if (process.env.WEBSITE_CMS_OWNER_API_ENABLED !== "true" ||
      process.env.WEBSITE_CMS_OWNER_DB_RLS_VERIFIED !== "true") {
    return ownerResponse({ error: "Owner API unavailable" }, 503);
  }
  const actor = await authenticateOwner(request);
  if (!actor) return ownerResponse({ error: "Authentication required" }, 401);
  if (!actor.permissions.includes(permission)) return ownerResponse({ error: "Insufficient permission" }, 403);
  return actor;
}
export function checkMutationRequest(request: Request): NextResponse | null {
  const expected = process.env.WEBSITE_CANONICAL_ORIGIN;
  if (!expected || request.headers.get("origin") !== expected) {
    return ownerResponse({ error: "Origin not allowed" }, 403);
  }
  if (!(request.headers.get("content-type") ?? "").startsWith("application/json")) {
    return ownerResponse({ error: "JSON required" }, 415);
  }
  const length = Number(request.headers.get("content-length") ?? 0);
  if (!Number.isFinite(length) || length < 0 || length > 110_000) {
    return ownerResponse({ error: "Body exceeds limit" }, 413);
  }
  return null;
}
export async function bodyJson(request: Request): Promise<unknown> {
  const raw = await request.text();
  if (raw.length > 110_000) throw new Error("Body exceeds limit");
  return JSON.parse(raw) as unknown;
}
export function draftFromUnknown(value: unknown): DraftDocument | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const object = value as Record<string, unknown>;
  if (typeof object.title !== "string" || !object.title.trim() || object.title.length > 180 ||
      typeof object.description !== "string" || object.description.length > 500 ||
      !Array.isArray(object.blocks) || object.blocks.length > 100) return null;
  const blocks = object.blocks;
  if (JSON.stringify(blocks).length > 100_000 || !validBuilderIdentities(blocks)) return null;
  if (!blocks.every(block => {
    if (!block || typeof block !== "object" || Array.isArray(block)) return false;
    const item = block as Record<string, unknown>;
    if (item.type === "heading" || item.type === "paragraph") return typeof item.text === "string" && !!item.text.trim() && item.text.length <= 10000;
    if (item.type === "image")
      return typeof item.assetId === "string" &&
        /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(item.assetId) &&
        typeof item.alt === "string" && !!item.alt.trim() && item.alt.length <= 300 &&
        typeof item.caption === "string" && item.caption.length <= 500;
    if (item.type === "hero" || item.type === "cta" || item.type === "faq")
      return validBuilderSection(item);
    if (item.type === "callout") return typeof item.title === "string" && !!item.title.trim() && item.title.length <= 180 &&
      typeof item.body === "string" && item.body.length <= 10000;
    return false;
  })) return null;
  return { title: object.title, description: object.description, blocks: blocks as DraftDocument["blocks"] };
}
