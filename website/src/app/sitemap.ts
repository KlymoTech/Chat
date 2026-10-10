import type { MetadataRoute } from "next";
import { publicRoutes, publishedOrigin } from "../lib/seo";
import { loadPublishedResources } from "../lib/cms-db";

export const dynamic="force-dynamic";
/**
 * A route appears only when indexing is approved and the public CMS view
 * currently returns a validated published revision. Trashed pages are
 * excluded by the database view; draft/private pages never enter the list.
 */
export default async function sitemap():Promise<MetadataRoute.Sitemap>{
  const origin=publishedOrigin();
  if(!origin)return [];
  const base=publicRoutes.map(path=>({url:new URL(path,origin).toString()}));
  const published=await loadPublishedResources();
  const urls=[...new Set(published.map(item=>item.path))];
  return [...base,...urls.map(path=>({url:new URL(path,origin).toString()}))];
}
