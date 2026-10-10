import {beforeEach,afterEach,describe,expect,it,vi} from "vitest";
vi.mock("server-only",()=>({}));
const fake=vi.hoisted(()=>({query:vi.fn(),release:vi.fn()}));
vi.mock("pg",()=>({Pool:class{connect(){return Promise.resolve(fake);}}}));
import {decideMediaPublication} from "../src/lib/media-publication";
import type {CmsActor} from "../src/lib/cms-editor";

const assetId="550e8400-e29b-41d4-a716-446655440000";
const siteId="62a2a2bf-1b2a-4fe2-a333-12b2a2a2a2a2";
const publisherId="e6a94037-1088-4898-b2f8-72f05a4b93aa";
const creatorId="f06035b4-90b6-42f3-b77a-41bf024feac0";
const reviewerId="a124aacc-19db-411a-a1a2-5a210deac46a";
const actor:CmsActor={id:publisherId,siteId,permissions:["cms:media:publish"]};
const clean=()=>({
  state:"approved",created_by_actor_id:creatorId,
  reviewed_by_actor_id:reviewerId,scanned_at:"2026-10-01",
  inspected_at:"2026-10-01",sanitized_key:"processed/private/candidate.webp",
  sanitized_sha256:"a".repeat(64),sanitized_byte_size:"200",
  published_at:null as string|null,withdrawn_at:null as string|null,
  alt_default:"Alt description",rights_statement:"Owned by site",
});
let row:ReturnType<typeof clean>;
let livePageCount=0;
beforeEach(()=>{
  vi.stubEnv("WEBSITE_MEDIA_PUBLICATION_ENABLED","true");
  vi.stubEnv("WEBSITE_MEDIA_PUBLISH_DB_ROLE_VERIFIED","true");
  vi.stubEnv("WEBSITE_MEDIA_PUBLICATION_DATABASE_URL","postgres://test:test@localhost/db");
  row=clean();livePageCount=0;fake.query.mockReset();fake.release.mockReset();
  fake.query.mockImplementation(async(sql:string)=>{
    if(sql.includes("SELECT state,created_by_actor_id"))return {rows:[row],rowCount:1};
    if(sql.includes("COUNT(*)::integer AS total"))return {rows:[{total:livePageCount}],rowCount:1};
    if(sql.includes("UPDATE website_cms.media_assets"))return {rowCount:1};
    return {rowCount:0};
  });
});
afterEach(()=>vi.unstubAllEnvs());
describe("independent media publication decisions",()=>{
  it("requires separate signed permission",async()=>{
    await expect(decideMediaPublication({...actor,permissions:["cms:media"]},
      assetId,"publish","Documented image publication")).rejects.toThrow(/permission/);
  });
  it("denies self-publication and missing scan evidence",async()=>{
    row.created_by_actor_id=publisherId;
    await expect(decideMediaPublication(actor,assetId,"publish",
      "Independently approved publishing")).rejects.toThrow(/Uploader/);
    row.created_by_actor_id=creatorId;row.inspected_at=null as unknown as string;
    await expect(decideMediaPublication(actor,assetId,"publish",
      "Independently approved publishing")).rejects.toThrow(/requirements/);
  });
  it("publishes only an approved record and appends attributable audit",async()=>{
    const outcome=await decideMediaPublication(actor,assetId,"publish",
      "Reviewed accessibility and legal rights");
    expect(outcome).toEqual({assetId,published:true,livePageCount:0});
    const update=fake.query.mock.calls.find(args=>String(args[0]).includes(
      "UPDATE website_cms.media_assets"));
    expect(String(update?.[0])).toContain("published_at=now()");
    expect(update?.[1]).toEqual([siteId,assetId,publisherId]);
    expect(fake.query.mock.calls.some(args=>String(args[0]).includes(
      "INSERT INTO website_cms.audit_events"))).toBe(true);
  });
  it("withdraws an active asset with a new audit entry, preserving source",async()=>{
    row.published_at="2026-10-01";
    expect(await decideMediaPublication(actor,assetId,"withdraw",
      "Remove published image pending legal review")).toEqual({
      assetId,published:false,livePageCount:0,
    });
    const update=fake.query.mock.calls.find(args=>String(args[0]).includes(
      "UPDATE website_cms.media_assets"));
    expect(String(update?.[0])).toContain("withdrawn_at=now()");
    expect(fake.query.mock.calls.some(args=>String(args[0]).includes(
      "DELETE FROM website_cms.media_assets"))).toBe(false);
  });
  it("requires impact acknowledgement when withdrawal affects active pages",async()=>{
    row.published_at="2026-10-01";
    livePageCount=2;
    await expect(decideMediaPublication(actor,assetId,"withdraw",
      "Urgent removal with active page references")).rejects.toThrow(/Acknowledge/);
    expect(fake.query.mock.calls.some(call=>
      String(call[0]).includes("UPDATE website_cms.media_assets"))).toBe(false);
    expect(await decideMediaPublication(actor,assetId,"withdraw",
      "Urgent removal with active page references",true)).toEqual({
      assetId,published:false,livePageCount:2,
    });
    const audit=fake.query.mock.calls.find(call=>
      String(call[0]).includes("INSERT INTO website_cms.audit_events"));
    expect(audit?.[1].slice(-2)).toEqual([2,true]);
  });
  it("rejects publishing already-public assets and withdrawing never-public ones",async()=>{
    row.published_at="2026-10-01";
    await expect(decideMediaPublication(actor,assetId,"publish",
      "Already on the public website")).rejects.toThrow(/already public/);
    row.published_at=null;
    await expect(decideMediaPublication(actor,assetId,"withdraw",
      "Trying to withdraw nonexistent publication")).rejects.toThrow(/not currently public/);
  });
});
