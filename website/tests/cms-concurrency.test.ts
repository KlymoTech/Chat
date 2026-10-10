import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
vi.mock("server-only",()=>({}));
const pg=vi.hoisted(()=>({query:vi.fn(),release:vi.fn()}));
vi.mock("pg",()=>({Pool:class{connect(){return Promise.resolve(pg);}}}));
import {saveDraft} from "../src/lib/cms-editor";
import type {CmsActor,DraftDocument} from "../src/lib/cms-editor";
const actor:CmsActor={
  id:"550e8400-e29b-41d4-a716-446655440000",
  siteId:"62a2a2bf-1b2a-4fe2-a333-12b2a2a2a2a2",
  permissions:["cms:draft"],
};
const pageId="e6a94037-1088-4898-b2f8-72f05a4b93aa";
const doc:DraftDocument={title:"Updated service page",description:"",
  blocks:[{type:"paragraph",text:"Reviewed content"}]};
beforeEach(()=>{
  vi.stubEnv("WEBSITE_CMS_EDITOR_DATABASE_URL","postgres://test:test@localhost/website_test");
  pg.query.mockReset();pg.release.mockReset();
  pg.query.mockImplementation(async(sql:string)=>{
    if(sql.includes("SELECT id FROM website_cms.pages"))return {rowCount:1,rows:[{id:pageId}]};
    if(sql.includes("COALESCE(MAX(revision_number)"))return {rowCount:1,rows:[{next:3}]};
    return {rowCount:1,rows:[]};
  });
});
afterEach(()=>vi.unstubAllEnvs());
describe("CMS optimistic revision save",()=>{
  it("rejects stale editors before any new revision or audit is written",async()=>{
    await expect(saveDraft(actor,pageId,doc,1)).rejects.toThrow(/revision conflict/);
    const actions=pg.query.mock.calls.map(call=>String(call[0]));
    expect(actions).toContain("ROLLBACK");
    expect(actions.some(s=>s.includes("INSERT INTO website_cms.page_revisions"))).toBe(false);
    expect(actions.some(s=>s.includes("INSERT INTO website_cms.audit_events"))).toBe(false);
    expect(pg.release).toHaveBeenCalled();
  });
  it("accepts only current expected revision and appends a new immutable draft",async()=>{
    const newId=await saveDraft(actor,pageId,doc,2);
    expect(newId).toMatch(/^[0-9a-f-]{36}$/);
    const insert=pg.query.mock.calls.find(call=>
      String(call[0]).includes("INSERT INTO website_cms.page_revisions"));
    expect(insert?.[1][2]).toBe(3);
    expect(pg.query.mock.calls.map(call=>String(call[0]))).toContain("COMMIT");
  });
  it("rejects missing, invalid or negative expected versions",async()=>{
    for(const expected of [0,-1,NaN,1.5,undefined]){
      await expect(saveDraft(actor,pageId,doc,expected as number)).rejects.toThrow(/Expected CMS revision/);
    }
  });
});
