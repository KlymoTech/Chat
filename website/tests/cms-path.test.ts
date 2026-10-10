import { describe, expect, it } from "vitest";
import { normalizeCmsPath } from "../src/lib/cms-path";

describe("website CMS route isolation", () => {
  it("accepts only canonical content slugs", () => {
    expect(normalizeCmsPath("/content/new-page")).toBe("/content/new-page");
    expect(normalizeCmsPath("/CONTENT/New-Page")).toBe("/content/new-page");
  });
  it("rejects reserved, malformed and nested routes", () => {
    for (const candidate of [
      "/", "/admin", "/api/leads", "/contact", "/content", "/content/a/b",
      "/content/../admin", "/content//hello", "/content/hello?q=1",
      "/content/a%2Fb", "/content/a_b", "https://example.com/content/abc"
    ]) expect(normalizeCmsPath(candidate)).toBeNull();
  });
  it("rejects invalid types and oversized paths", () => {
    expect(normalizeCmsPath(null)).toBeNull();
    expect(normalizeCmsPath("/content/"+"a".repeat(520))).toBeNull();
  });
});
