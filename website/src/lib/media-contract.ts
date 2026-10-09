/** Strict intake manifest. This validates claims, NOT the underlying file bytes. */
export const MEDIA_MIME_ALLOWLIST = [
  "image/jpeg","image/png","image/webp","image/avif",
] as const;
export type MediaMime = typeof MEDIA_MIME_ALLOWLIST[number];
export type MediaManifest = Readonly<{
  originalFilename: string;
  claimedMime: MediaMime;
  claimedSha256: string;
  claimedByteSize: number;
  altDefault: string;
  rightsStatement: string;
  provenance: Readonly<{
    source: "original" | "licensed" | "ai-generated";
    credit: string;
    generationTool: string;
  }>;
}>;
const fileName = /^[a-zA-Z0-9][a-zA-Z0-9 _.,()\-]{0,254}$/;
const sha256 = /^[0-9a-f]{64}$/;
const extensions: Record<MediaMime,readonly string[]> = {
  "image/jpeg":["jpg","jpeg"],"image/png":["png"],
  "image/webp":["webp"],"image/avif":["avif"],
};
export function parseMediaManifest(value: unknown): MediaManifest | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const data = value as Record<string,unknown>;
  const originalFilename = data.originalFilename;
  const claimedMime = data.claimedMime;
  const claimedSha256 = data.claimedSha256;
  const claimedByteSize = data.claimedByteSize;
  const altDefault = data.altDefault;
  const rightsStatement = data.rightsStatement;
  if (typeof originalFilename !== "string" ||
      originalFilename.length > 255 || !fileName.test(originalFilename) ||
      typeof claimedMime !== "string" ||
      !MEDIA_MIME_ALLOWLIST.includes(claimedMime as MediaMime) ||
      !extensions[claimedMime as MediaMime]?.some(ext =>
        originalFilename.toLowerCase().endsWith("." + ext)) ||
      typeof claimedSha256 !== "string" || !sha256.test(claimedSha256) ||
      typeof claimedByteSize !== "number" ||
      !Number.isSafeInteger(claimedByteSize) || claimedByteSize < 1 ||
      claimedByteSize > 10*1024*1024 ||
      typeof altDefault !== "string" || altDefault.length > 300 ||
      typeof rightsStatement !== "string" || rightsStatement.length > 500) return null;
  const provenance = data.provenance;
  if (!provenance || typeof provenance !== "object" || Array.isArray(provenance)) return null;
  const p = provenance as Record<string,unknown>;
  if (p.source !== "original" && p.source !== "licensed" && p.source !== "ai-generated") return null;
  if (typeof p.credit !== "string" || p.credit.length > 300 ||
      typeof p.generationTool !== "string" || p.generationTool.length > 200 ||
      (p.source === "licensed" && !p.credit.trim()) ||
      (p.source === "ai-generated" && !p.generationTool.trim())) return null;
  return {
    originalFilename,
    claimedMime: claimedMime as MediaMime,
    claimedSha256, claimedByteSize,
    altDefault:altDefault.trim(),
    rightsStatement:rightsStatement.trim(),
    provenance:{
      source:p.source as MediaManifest["provenance"]["source"],
      credit:p.credit.trim(),generationTool:p.generationTool.trim(),
    },
  };
}
