import { site } from "./site";

/** Never invite indexing for local, staging or unapproved deployments. */
export function publishedOrigin(): URL | null {
  const raw = process.env.NEXT_PUBLIC_SITE_URL;
  if (!raw) return null;
  try {
    const url = new URL(raw);
    if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash || url.pathname !== "/") return null;
    if (["localhost", "127.0.0.1", "0.0.0.0"].includes(url.hostname) || url.hostname.endsWith(".local")) return null;
    if (process.env.NEXT_PUBLIC_SITE_APPROVED !== "true") return null;
    return url;
  } catch { return null; }
}

export function canonical(path: string): string | undefined {
  const origin = publishedOrigin();
  return origin ? new URL(path, origin).toString() : undefined;
}

export const publicRoutes = ["/", "/services", "/about", "/resources", "/blog", "/contact"] as const;
export const indexingApproved = () => Boolean(publishedOrigin());
export const publicSiteName = site.name;
