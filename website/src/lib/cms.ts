/** Read-only public CMS contract. Never return draft data to public visitors. */
export type PublicBlock =
  | { type: "heading"; text: string }
  | { type: "paragraph"; text: string }
  | { type: "callout"; title: string; body: string };

export type PublishedPage = {
  id: string;
  path: string;
  locale: string;
  revision: number;
  title: string;
  description: string;
  blocks: PublicBlock[];
};

const allowedBlockTypes = new Set(["heading", "paragraph", "callout"]);
export function isPublishedPage(value: unknown): value is PublishedPage {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const page = value as Record<string, unknown>;
  return typeof page.id === "string" && typeof page.path === "string" && page.path.startsWith("/")
    && typeof page.locale === "string" && typeof page.revision === "number"
    && Number.isSafeInteger(page.revision) && page.revision > 0
    && typeof page.title === "string" && typeof page.description === "string"
    && Array.isArray(page.blocks) && page.blocks.every(block => {
      if (!block || typeof block !== "object") return false;
      const item = block as Record<string, unknown>;
      if (typeof item.type !== "string" || !allowedBlockTypes.has(item.type)) return false;
      return item.type === "callout" ? typeof item.title === "string" && typeof item.body === "string"
        : typeof item.text === "string";
    });
}

/** Server-side API fetch; deliberately does not expose admin credentials. */
export async function getPublishedPage(path: string, locale = "en"): Promise<PublishedPage | null> {
  const base = process.env.WEBSITE_CMS_PUBLIC_API_URL;
  if (!base || !path.startsWith("/") || path.includes("?") || path.includes("#")) return null;
  const endpoint = new URL("/public/pages", base);
  endpoint.searchParams.set("path", path);
  endpoint.searchParams.set("locale", locale);
  try {
    const response = await fetch(endpoint, { cache: "no-store", signal: AbortSignal.timeout(3500) });
    if (!response.ok) return null;
    const data: unknown = await response.json();
    return isPublishedPage(data) && data.path === path && data.locale === locale ? data : null;
  } catch { return null; }
}
