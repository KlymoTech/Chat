import {beforeEach,afterEach,describe,expect,it,vi} from "vitest";
vi.mock("server-only",()=>({}));
const fake=vi.hoisted(()=>({connect:vi.fn(),query:vi.fn(),release:vi.fn()}));
vi.mock("pg",()=>({Pool:class{connect(){return fake.connect();}}}));
import {recordOptionalAnalytics} from "../src/lib/analytics-server";

const receiptId="550e8400-e29b-41d4-a716-446655440000";
const event={eventName:"cta_click" as const,actionKey:"cta_contact",routePath:"/contact"};
beforeEach(()=>{
  vi.stubEnv("WEBSITE_ANALYTICS_COLLECTION_ENABLED","true");
  vi.stubEnv("WEBSITE_CMS_SITE_SLUG","example-site");
  fake.connect.mockReset();fake.query.mockReset();fake.release.mockReset();
});
afterEach(()=>vi.unstubAllEnvs());
describe("optional analytics cannot crash a public request",()=>{
  it("suppresses events before connecting if analytics collection is off",async()=>{
    vi.stubEnv("WEBSITE_ANALYTICS_COLLECTION_ENABLED","false");
    expect(await recordOptionalAnalytics(receiptId,event)).toBe(false);
    expect(fake.connect).not.toHaveBeenCalled();
  });
  it("returns false, not a thrown error, when consent DB isn't configured",async()=>{
    vi.stubEnv("WEBSITE_CONSENT_RECORDS_ENABLED","false");
    expect(await recordOptionalAnalytics(receiptId,event)).toBe(false);
    expect(fake.connect).not.toHaveBeenCalled();
  });
  it("suppresses the event when an enabled DB refuses connection",async()=>{
    vi.stubEnv("WEBSITE_CONSENT_RECORDS_ENABLED","true");
    vi.stubEnv("WEBSITE_PRIVACY_DB_GRANTS_VERIFIED","true");
    vi.stubEnv("WEBSITE_PRIVACY_DATABASE_URL","postgres://localhost/test");
    fake.connect.mockRejectedValue(new Error("Database unavailable"));
    expect(await recordOptionalAnalytics(receiptId,event)).toBe(false);
  });
  it("rolls back and never inserts events without a valid current receipt",async()=>{
    vi.stubEnv("WEBSITE_CONSENT_RECORDS_ENABLED","true");
    vi.stubEnv("WEBSITE_PRIVACY_DB_GRANTS_VERIFIED","true");
    vi.stubEnv("WEBSITE_PRIVACY_DATABASE_URL","postgres://localhost/test");
    fake.connect.mockResolvedValue({query:fake.query,release:fake.release});
    fake.query.mockImplementation(async(sql:string)=>String(sql).includes("SELECT c.site_id")?
      {rowCount:0,rows:[]}:{rowCount:1,rows:[]});
    expect(await recordOptionalAnalytics(receiptId,event)).toBe(false);
    expect(fake.query.mock.calls.map(call=>call[0])).toContain("ROLLBACK");
    expect(fake.query.mock.calls.some(call=>
      String(call[0]).includes("INSERT INTO website_cms.analytics_events"))).toBe(false);
    expect(fake.release).toHaveBeenCalledTimes(1);
  });
});
