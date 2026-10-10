import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
vi.mock("server-only",()=>({}));
const fake=vi.hoisted(()=>({query:vi.fn(),release:vi.fn()}));
vi.mock("pg",()=>({Pool:class{connect(){return Promise.resolve(fake);}}}));
import {reviewPrivateMedia} from "../src/lib/media-review";
import type {CmsActor} from "../src/lib/cms-editor";

const siteId="550e8400-e29b-41d4-a716-446655440000";
const reviewerId="62a2a2bf-1b2a-4fe2-a333-12b2a2a2a2a2";
const creatorId="e6a94037-1088-4898-b2f8-72f05a4b93aa";
const assetId="f06035b4-90b6-42f3-b77a-41bf024feac0";
const actor:CmsActor={id:reviewerId,siteId,permissions:["cms:media:review"]};
function cleanRow(){
  return {
    created_by_actor_id:creatorId,state:"quarantined",blob_status:"uploaded",
    scanned_at:"2026-10-10T10:00:00Z",inspected_at:"2026-10-10T10:00:00Z",
    scan_engine:"clamav-instream",sanitized_key:"processed/site/file/candidate.webp",
    sanitized_sha256:"a".repeat(64),sanitized_byte_size:"200",
    scanner_receipt_sha256:"b".repeat(64),
    detected_mime:"image/webp",verified_sha256:"c".repeat(64),
    verified_byte_size:"400",claimed_mime:"image/webp",
    claimed_sha256:"c".repeat(64),claimed_byte_size:"400",
    alt_default:"Descriptive image",rights_statement:"Publisher owns artwork",
  };
}
let row:ReturnType<typeof cleanRow>;
beforeEach(()=>{
  vi.stubEnv("WEBSITE_MEDIA_REVIEW_ENABLED","true");
  vi.stubEnv("WEBSITE_MEDIA_REVIEW_DB_ROLE_VERIFIED","true");
  vi.stubEnv("WEBSITE_MEDIA_REVIEW_DATABASE_URL","postgres://test:test@localhost/media");
  row=cleanRow();
  fake.query.mockReset();fake.release.mockReset();
  fake.query.mockImplementation(async (sql:string)=>{
    if(sql.includes("SELECT created_by_actor_id"))return {rows:[row],rowCount:1};
    if(sql.includes("UPDATE website_cms.media_assets"))return {rowCount:1};
    return {rowCount:0};
  });
});
afterEach(()=>vi.unstubAllEnvs());

describe("independent private media review",()=>{
  it("rejects self-approval and never updates state",async()=>{
    row.created_by_actor_id=reviewerId;
    await expect(reviewPrivateMedia(actor,assetId,"approve",
      "Reviewed the image independently","a".repeat(64))).rejects.toThrow(/Creator cannot/);
    expect(fake.query.mock.calls.filter(c=>String(c[0]).includes("UPDATE website_cms.media_assets"))).toHaveLength(0);
  });
  it("rejects approval when scan evidence is incomplete",async()=>{
    row.scanned_at=null as unknown as string;
    await expect(reviewPrivateMedia(actor,assetId,"approve",
      "Requires complete inspection evidence","a".repeat(64))).rejects.toThrow(/has not passed/);
  });
  it("records independent approval without public delivery",async()=>{
    const result=await reviewPrivateMedia(actor,assetId,"approve",
      "Rights and scan evidence independently verified","a".repeat(64));
    expect(result).toEqual({assetId,state:"approved",publicAccess:false});
    const update=fake.query.mock.calls.find(c=>String(c[0]).includes("UPDATE website_cms.media_assets"));
    expect(update?.[1][2]).toBe("approved");
    expect(update?.[1][3]).toBe(reviewerId);
    expect(fake.query.mock.calls.some(c=>String(c[0]).includes("INSERT INTO website_cms.audit_events"))).toBe(true);
  });
  it("blocks approval if the reviewed derivative hash changed",async()=>{
    await expect(reviewPrivateMedia(actor,assetId,"approve",
      "Reviewed image must match the current stored bytes","f".repeat(64)
    )).rejects.toThrow(/checksum/);
  });
  it("allows independent rejection of unscanned content without deletion",async()=>{
    row.scanned_at=null as unknown as string;
    const result=await reviewPrivateMedia(actor,assetId,"reject",
      "Unclear rights and cannot use this artwork");
    expect(result.state).toBe("rejected");
    expect(result.publicAccess).toBe(false);
  });
  it("denies reviewers without the distinct review claim",async()=>{
    const author:CmsActor={...actor,permissions:["cms:media"]};
    await expect(reviewPrivateMedia(author,assetId,"approve",
      "A reason that is long enough")).rejects.toThrow(/permission/);
  });
});
