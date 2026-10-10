import {validBuilderIdentities,validBuilderSection,type BuilderIdentity,type BuilderSection} from "./builder-contract";
/** Read-only public CMS contract. Render only inert, allowlisted blocks. */
export type PublicBlock =
  | (BuilderIdentity & { type: "heading"; text: string })
  | (BuilderIdentity & { type: "paragraph"; text: string })
  | (BuilderIdentity & { type: "callout"; title: string; body: string })
  | (BuilderIdentity & { type: "image"; assetId: string; alt: string; caption: string })
  | BuilderSection;

export type PublishedPage = {
  id: string;
  path: string;
  locale: string;
  revision: number;
  title: string;
  description: string;
  blocks: PublicBlock[];
};

const safeText = (value: unknown, max: number) =>
  typeof value === "string" && value.length <= max;
export function isPublishedPage(value: unknown): value is PublishedPage {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const page = value as Record<string, unknown>;
  return typeof page.id === "string" && /^[0-9a-f-]{36}$/i.test(page.id)
    && typeof page.path === "string" && /^\/[a-z0-9/-]{0,511}$/.test(page.path)
    && typeof page.locale === "string" && /^[a-z]{2}(?:-[A-Z]{2})?$/.test(page.locale)
    && Number.isSafeInteger(page.revision) && (page.revision as number) > 0
    && safeText(page.title, 180) && (page.title as string).trim().length > 0
    && safeText(page.description, 500)
    && Array.isArray(page.blocks) && page.blocks.length <= 100 && validBuilderIdentities(page.blocks)
    && page.blocks.every(block => {
      if (!block || typeof block !== "object" || Array.isArray(block)) return false;
      const item = block as Record<string, unknown>;
      if (item.type === "heading" || item.type === "paragraph") {
        return safeText(item.text, 10000) && (item.text as string).trim().length > 0;
      }
      if (item.type === "image") {
        return typeof item.assetId === "string" &&
          /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(item.assetId) &&
          safeText(item.alt, 300) && (item.alt as string).trim().length > 0 &&
          safeText(item.caption, 500);
      }
      if (item.type === "hero" || item.type === "cta" || item.type === "faq") {
        return validBuilderSection(item);
      }
      if (item.type === "callout") {
        return safeText(item.title, 180) && (item.title as string).trim().length > 0
          && safeText(item.body, 10000);
      }
      return false;
    });
}

/** Optional server-side published-only provider adapter. */
export async function getPublishedPage(path: string, locale = "en"): Promise<PublishedPage | null> {
  const base = process.env.WEBSITE_CMS_PUBLIC_API_URL;
  if (!base || !/^\/[a-z0-9/-]{0,511}$/.test(path) || !/^[a-z]{2}(?:-[A-Z]{2})?$/.test(locale)) return null;
  // Never follow a URL supplied by a visitor: base must come from server configuration.
  let endpoint: URL;
  try {
    endpoint = new URL("/public/pages", base);
    if (!["http:", "https:"].includes(endpoint.protocol) || endpoint.username || endpoint.password) return null;
  } catch { return null; }
  endpoint.searchParams.set("path", path);
  endpoint.searchParams.set("locale", locale);
  try {
    const response = await fetch(endpoint, { cache: "no-store", signal: AbortSignal.timeout(3500) });
    if (!response.ok) return null;
    const data: unknown = await response.json();
    return isPublishedPage(data) && data.path === path && data.locale === locale ? data : null;
  } catch { return null; }
}
