import type { MetadataRoute } from "next";
import { publicRoutes, publishedOrigin } from "../lib/seo";

export default function sitemap(): MetadataRoute.Sitemap {
  const origin = publishedOrigin();
  if (!origin) return [];
  // Only publicly approved, stable routes: drafts, legal placeholders and private screens stay out.
  return publicRoutes.map(path => ({ url: new URL(path, origin).toString(), changeFrequency: "monthly" as const }));
}
