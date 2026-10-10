import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

const query = vi.hoisted(() => vi.fn());
vi.mock("server-only", () => ({}));
vi.mock("pg", () => ({Pool: class { query(...args:unknown[]) {return query(...args);} }}));

import { checkPublicCmsReadiness, publicReadinessConfigured } from "../src/lib/public-readiness";

beforeEach(()=>{
  vi.stubEnv("WEBSITE_RUNTIME_READINESS_ENABLED","true");
  vi.stubEnv("WEBSITE_CMS_SITE_SLUG","sample-site");
  vi.stubEnv("WEBSITE_CMS_DATABASE_URL","postgres://public-read-only@example.invalid/db");
  query.mockReset();
});
afterEach(()=>vi.unstubAllEnvs());

describe("public CMS dependency readiness",()=>{
  it("fails closed when disabled or unconfigured",async()=>{
    vi.stubEnv("WEBSITE_RUNTIME_READINESS_ENABLED","false");
    expect(await checkPublicCmsReadiness()).toBe("unavailable");
    expect(query).not.toHaveBeenCalled();
  });
  it("rejects invalid site scopes and database connection strings",()=>{
    for (const readerUrl of ["", " ", "https://example.com/db", "postgres://", "postgres://db/", "not a URL"]) {
      expect(publicReadinessConfigured({enabled:"true",siteSlug:"site-one",readerUrl})).toBe(false);
    }
    expect(publicReadinessConfigured({
      enabled:"true",siteSlug:"../other-site",readerUrl:"postgres://db/site",
    })).toBe(false);
    expect(publicReadinessConfigured({
      enabled:"true",siteSlug:"site-one",readerUrl:"postgres://db/site",
    })).toBe(true);
    expect(publicReadinessConfigured({
      enabled:"true",siteSlug:"site-one",readerUrl:"postgresql://db/site",
    })).toBe(true);
  });
  it("reports a healthy public published view without looking at private tables",async()=>{
    query.mockResolvedValue({rows:[]});
    expect(await checkPublicCmsReadiness()).toBe("ready");
    expect(query).toHaveBeenCalledWith(
      "SELECT 1 FROM website_cms.public_published_pages LIMIT 0");
  });
  it("returns unavailable without leaking database diagnostics",async()=>{
    query.mockRejectedValue(new Error("secret reader host name"));
    expect(await checkPublicCmsReadiness()).toBe("unavailable");
  });
});
