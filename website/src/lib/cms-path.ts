/** Canonical CMS routes. Reserved application endpoints cannot be overridden. */
const RESERVED = new Set([
  "/", "/about", "/services", "/resources", "/contact",
  "/privacy", "/terms", "/privacy-choices", "/admin", "/api"
]);
export function normalizeCmsPath(input: unknown): string | null {
  if (typeof input !== "string" || input.length > 512) return null;
  const path = input.trim().toLowerCase();
  if (!/^\/[a-z0-9]+(?:[-/][a-z0-9]+)*$/.test(path)) return null;
  if (path.includes("//") || path.includes("..") || RESERVED.has(path)) return null;
  if (path === "/content" || !path.startsWith("/content/")) return null;
  if (path.split("/").length !== 3) return null;
  return path;
}
