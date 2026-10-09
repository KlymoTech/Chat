import type { MetadataRoute } from "next";
import { publishedOrigin } from "../lib/seo";

export default function robots(): MetadataRoute.Robots {
  const origin = publishedOrigin();
  if (!origin) return { rules: { userAgent: "*", disallow: "/" } };
  return {
    rules: [{ userAgent: "*", allow: "/", disallow: ["/api/", "/admin/", "/owner", "/owner/", "/preview/"] }],
    sitemap: new URL("/sitemap.xml", origin).toString(),
  };
}
