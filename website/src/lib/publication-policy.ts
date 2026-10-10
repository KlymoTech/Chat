import { isPublishedPage } from "./cms";

export type PublicResourceSummary = {
  path: string;
  title: string;
  description: string;
};

/** A public index must never advertise malformed, private or duplicate paths. */
export function collectPublicResources(
  candidates: readonly unknown[],
  locale: string,
): PublicResourceSummary[] {
  if (!/^[a-z]{2}(?:-[A-Z]{2})?$/.test(locale)) return [];
  const seen = new Set<string>();
  const visible: PublicResourceSummary[] = [];
  for (const candidate of candidates.slice(0, 100)) {
    if (!isPublishedPage(candidate) || candidate.locale !== locale ||
        !/^\/content\/[a-z0-9]+(?:-[a-z0-9]+)*$/.test(candidate.path) ||
        seen.has(candidate.path)) continue;
    seen.add(candidate.path);
    visible.push({
      path: candidate.path,
      title: candidate.title,
      description: candidate.description,
    });
  }
  return visible;
}
