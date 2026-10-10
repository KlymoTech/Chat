import {afterEach,describe,expect,it,vi} from "vitest";
import {attachPublishedMediaUsages,mediaAssetIds} from "../src/lib/editor-media-links";
import type {CmsBlock} from "../src/lib/cms-editor";
import type {PoolClient} from "pg";

const siteId="62a2a2bf-1b2a-4fe2-a333-12b2a2a2a2a2";
const assetId="550e8400-e29b-41d4-a716-446655440000";
const pageId="e6a94037-1088-4898-b2f8-72f05a4b93aa";
const revisionId="f06035b4-90b6-42f3-b77a-41bf024feac0";
const blocks:CmsBlock[]=[
  {type:"paragraph",text:"Intro"},
  {type:"image",assetId,alt:"Relevant description",caption:"Caption"},
  {type:"image",assetId,alt:"Same image again",caption:""},
];
afterEach(()=>vi.unstubAllEnvs());
describe("CMS media publication gates",()=>{
  it("deduplicates image usage and ignores ordinary text blocks",()=>{
    expect(mediaAssetIds(blocks)).toEqual([assetId]);
    expect(mediaAssetIds([{type:"heading",text:"No media"}])).toEqual([]);
  });
  it("blocks media references while public delivery is disabled",async()=>{
    vi.stubEnv("WEBSITE_MEDIA_PUBLIC_DELIVERY_ENABLED","false");
    const query=vi.fn();
    await expect(attachPublishedMediaUsages({query} as unknown as PoolClient,
      siteId,pageId,revisionId,blocks)).rejects.toThrow(/not enabled/);
    expect(query).not.toHaveBeenCalled();
  });
  it("refuses withdrawn and cross-site media, never inserting usage",async()=>{
    vi.stubEnv("WEBSITE_MEDIA_PUBLIC_DELIVERY_ENABLED","true");
    vi.stubEnv("WEBSITE_MEDIA_PUBLIC_READER_GRANTS_VERIFIED","true");
    const query=vi.fn().mockResolvedValue({rowCount:0});
    await expect(attachPublishedMediaUsages({query} as unknown as PoolClient,
      siteId,pageId,revisionId,blocks)).rejects.toThrow(/private, withdrawn/);
    expect(query).toHaveBeenCalledTimes(1);
    expect(query.mock.calls[0][1]).toEqual([assetId,siteId]);
  });
  it("records one immutable usage after checking exact site and public status",async()=>{
    vi.stubEnv("WEBSITE_MEDIA_PUBLIC_DELIVERY_ENABLED","true");
    vi.stubEnv("WEBSITE_MEDIA_PUBLIC_READER_GRANTS_VERIFIED","true");
    const query=vi.fn().mockResolvedValue({rowCount:1});
    await attachPublishedMediaUsages({query} as unknown as PoolClient,
      siteId,pageId,revisionId,blocks);
    expect(query).toHaveBeenCalledTimes(2);
    expect(String(query.mock.calls[0][0])).toContain("withdrawn_at IS NULL");
    expect(String(query.mock.calls[1][0])).toContain("website_cms.media_usages");
    expect(query.mock.calls[1][1]).toEqual([siteId,assetId,pageId,revisionId]);
  });
});
