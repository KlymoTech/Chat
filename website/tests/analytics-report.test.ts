import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
vi.mock("server-only",()=>({}));
const fake=vi.hoisted(()=>({query:vi.fn()}));
vi.mock("pg",()=>({Pool:class{query(...args:unknown[]){return fake.query(...args);}}}));
import {getAnalyticsSummary} from "../src/lib/analytics-report";
import type {CmsActor} from "../src/lib/cms-editor";

const actor:CmsActor={
  id:"62a2a2bf-1b2a-4fe2-a333-12b2a2a2a2a2",
  siteId:"550e8400-e29b-41d4-a716-446655440000",
  permissions:["cms:read"],
};
beforeEach(()=>{
  vi.stubEnv("WEBSITE_ANALYTICS_REPORTING_ENABLED","true");
  vi.stubEnv("WEBSITE_ANALYTICS_READ_GRANTS_VERIFIED","true");
  vi.stubEnv("WEBSITE_ANALYTICS_REPORT_DATABASE_URL","postgres://reader:secret@localhost/website_test");
  fake.query.mockReset();
  fake.query.mockResolvedValue({rows:[],rowCount:0});
});
afterEach(()=>vi.unstubAllEnvs());
describe("private aggregate analytics",()=>{
  it("returns only bounded site-scoped, consent-current anonymous groups",async()=>{
    expect(await getAnalyticsSummary(actor)).toEqual([]);
    const [sql,params]=fake.query.mock.calls[0];
    expect(params).toEqual([actor.siteId]);
    expect(String(sql)).toContain("c.withdrawn_at IS NULL");
    expect(String(sql)).toContain("c.expires_at>now()");
    expect(String(sql)).toContain("c.analytics_allowed=true");
    expect(String(sql)).toContain("HAVING COUNT(*)>=5");
    expect(String(sql)).toContain("LIMIT 200");
  });
  it("requires a verified reporting gate and owner read permission",async()=>{
    await expect(getAnalyticsSummary({...actor,permissions:[]})).rejects.toThrow(/disabled/);
    vi.stubEnv("WEBSITE_ANALYTICS_REPORTING_ENABLED","false");
    await expect(getAnalyticsSummary(actor)).rejects.toThrow(/disabled/);
  });
});
