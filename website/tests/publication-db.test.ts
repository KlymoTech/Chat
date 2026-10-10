import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fakeQuery = vi.hoisted(() => vi.fn());
vi.mock("server-only", () => ({}));
vi.mock("pg", () => ({
  Pool: class {
    query(...args: unknown[]) { return fakeQuery(...args); }
  },
}));

import { loadPublishedPage, readPublishedResources } from "../src/lib/cms-db";

const published = {
  id: "550e8400-e29b-41d4-a716-446655440000",
  path: "/content/published-guide",
  locale: "en",
  revision: 2,
  title: "Reviewed guide",
  description: "Approved and published",
  blocks: [{type: "paragraph",text:"Read-only public information"}],
};
beforeEach(() => {
  vi.stubEnv("WEBSITE_CMS_DATABASE_URL", "postgres://reader:nonsecret@localhost/example");
  vi.stubEnv("WEBSITE_CMS_SITE_SLUG", "example-site");
  fakeQuery.mockReset();
});
afterEach(() => vi.unstubAllEnvs());

describe("published-only PostgreSQL read adapter", () => {
  it("returns an exactly matched page from the published view", async () => {
    fakeQuery.mockResolvedValue({rows:[published]});
    expect(await loadPublishedPage("/content/published-guide")).toEqual(published);
    const [sql, parameters] = fakeQuery.mock.calls[0];
    expect(String(sql)).toContain("website_cms.public_published_pages");
    expect(parameters).toEqual(["example-site","/content/published-guide","en"]);
  });
  it("rejects mismatched routes and locales even if a DB view is misconfigured", async () => {
    fakeQuery.mockResolvedValue({rows:[published]});
    expect(await loadPublishedPage("/content/a-different-guide")).toBeNull();
    expect(await loadPublishedPage("/content/published-guide","fr")).toBeNull();
  });
  it("does not treat an empty library as a database outage", async () => {
    fakeQuery.mockResolvedValue({rows:[]});
    expect(await readPublishedResources()).toEqual({status:"ready",resources:[]});
  });
  it("reports DB errors as unavailable without leaking diagnostics", async () => {
    fakeQuery.mockRejectedValue(new Error("database hostname and password must stay private"));
    expect(await readPublishedResources()).toEqual({status:"unavailable",resources:[]});
  });
  it("lists only valid public-view entries with no raw blocks", async () => {
    fakeQuery.mockResolvedValue({rows:[
      published,
      {...published,path:"/owner",title:"Secret draft"},
      {...published,locale:"fr",path:"/content/french"},
    ]});
    expect(await readPublishedResources()).toEqual({
      status:"ready",
      resources:[{
        path:"/content/published-guide",
        title:"Reviewed guide",
        description:"Approved and published"
      }],
    });
  });
});
