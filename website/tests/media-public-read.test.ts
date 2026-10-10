import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
import {createHash} from "node:crypto";

const fake=vi.hoisted(()=>({query:vi.fn(),send:vi.fn()}));
vi.mock("server-only",()=>({}));
vi.mock("pg",()=>({Pool:class{query(...args:unknown[]){return fake.query(...args);}}}));
vi.mock("@aws-sdk/client-s3",()=>({
  S3Client:class{send(command:unknown){return fake.send(command);}destroy(){}},
  HeadObjectCommand:class{
    kind="head";input:unknown;
    constructor(input:unknown){this.input=input;}
  },
  GetObjectCommand:class{
    kind="get";input:unknown;
    constructor(input:unknown){this.input=input;}
  },
}));
import {loadPublicApprovedMedia} from "../src/lib/media-public-read";
const siteId="62a2a2bf-1b2a-4fe2-a333-12b2a2a2a2a2";
const assetId="550e8400-e29b-41d4-a716-446655440000";
const bytes=Buffer.from([0x52,0x49,0x46,0x46,0x08,0x00,0x00,0x00,0x57,0x45,0x42,0x50]);
const sha256=createHash("sha256").update(bytes).digest("hex");
const row={id:assetId,storage_key:"processed/"+siteId+"/"+assetId+"/candidate.webp",
  sha256,byte_size:String(bytes.length)};
beforeEach(()=>{
  vi.stubEnv("WEBSITE_MEDIA_PUBLIC_DELIVERY_ENABLED","true");
  vi.stubEnv("WEBSITE_MEDIA_PUBLIC_READER_GRANTS_VERIFIED","true");
  vi.stubEnv("WEBSITE_CMS_SITE_SLUG","site-a");
  vi.stubEnv("WEBSITE_MEDIA_PUBLIC_DATABASE_URL","postgres://read:pass@localhost/site");
  vi.stubEnv("WEBSITE_MEDIA_PUBLIC_STORAGE_ENDPOINT","https://media-storage.example-company.com/");
  vi.stubEnv("WEBSITE_MEDIA_PUBLIC_STORAGE_BUCKET","private-media-candidates");
  vi.stubEnv("WEBSITE_MEDIA_PUBLIC_STORAGE_REGION","us-east-1");
  vi.stubEnv("WEBSITE_MEDIA_PUBLIC_STORAGE_ACCESS_KEY_ID","reader-identity");
  vi.stubEnv("WEBSITE_MEDIA_PUBLIC_STORAGE_SECRET_ACCESS_KEY","reader-secret-long-enough-for-test");
  fake.query.mockReset();fake.send.mockReset();
  fake.query.mockResolvedValue({rowCount:1,rows:[row]});
  fake.send.mockImplementation(async (command:{kind:string})=>
    command.kind==="head"?{ContentLength:bytes.length,Metadata:{sha256}}:
      {Body:{async *[Symbol.asyncIterator](){yield bytes;}}});
});
afterEach(()=>vi.unstubAllEnvs());
describe("published-only media read adapter",()=>{
  it("never returns a byte when site reader gate is disabled",async()=>{
    vi.stubEnv("WEBSITE_MEDIA_PUBLIC_DELIVERY_ENABLED","false");
    expect(await loadPublicApprovedMedia(assetId)).toBeNull();
    expect(fake.query).not.toHaveBeenCalled();
  });
  it("reads only the scoped published media SQL view",async()=>{
    const media=await loadPublicApprovedMedia(assetId);
    expect(Buffer.from(media??[])).toEqual(bytes);
    const [sql,params]=fake.query.mock.calls[0];
    expect(String(sql)).toContain("website_cms.public_published_media");
    expect(params).toEqual(["site-a",assetId]);
    expect(fake.send.mock.calls.map(c=>c[0].kind)).toEqual(["head","get"]);
    expect((fake.send.mock.calls[0][0] as {input:{Key:string}}).input.Key)
      .toBe(row.storage_key);
  });
  it("fails closed if unpublished or object integrity is wrong",async()=>{
    fake.query.mockResolvedValue({rowCount:0,rows:[]});
    expect(await loadPublicApprovedMedia(assetId)).toBeNull();
    expect(fake.send).not.toHaveBeenCalled();
    fake.query.mockResolvedValue({rowCount:1,rows:[row]});
    fake.send.mockResolvedValue({ContentLength:bytes.length,Metadata:{sha256:"0".repeat(64)}});
    expect(await loadPublicApprovedMedia(assetId)).toBeNull();
  });
});
