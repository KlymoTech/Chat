import {beforeEach,afterEach,describe,expect,it,vi} from "vitest";
vi.mock("server-only",()=>({}));
const fake=vi.hoisted(()=>({query:vi.fn(),release:vi.fn(),connect:vi.fn()}));
vi.mock("pg",()=>({Pool:class{
 connect(){return fake.connect();}
 query(...args:unknown[]){return fake.query(...args);}
}}));
import {openRightsCase,advanceRightsCase,listRightsCases,readRightsCaseHistory}
  from "../src/lib/privacy-rights-service";
import type {CmsActor} from "../src/lib/cms-editor";
const actor:CmsActor={id:"550e8400-e29b-41d4-a716-446655440000",
 siteId:"62a2a2bf-1b2a-4fe2-a333-12b2a2a2a2a2",permissions:["cms:privacy"]};
const reviewer:CmsActor={...actor,id:"e6a94037-1088-4898-b2f8-72f05a4b93aa"};
const caseId="f06035b4-90b6-42f3-b77a-41bf024feac0";
const evidence="bda93026-118e-4e09-91f2-dbfda0bff2a3";
beforeEach(()=>{
  vi.stubEnv("WEBSITE_PRIVACY_RIGHTS_ENABLED","true");
  vi.stubEnv("WEBSITE_PRIVACY_RIGHTS_DB_GRANTS_VERIFIED","true");
  vi.stubEnv("WEBSITE_PRIVACY_RIGHTS_DATABASE_URL","postgres://test:pass@localhost/test");
  fake.query.mockReset();fake.release.mockReset();
  fake.connect.mockReset().mockResolvedValue({
    query:fake.query,release:fake.release,
  });
  fake.query.mockImplementation(async(sql:string)=>{
    if(String(sql).includes("FOR UPDATE"))return {rowCount:1,rows:[{
      status:"under_review",revision:3,created_by_actor_id:actor.id,
    }]};
    if(String(sql).includes("SELECT actor_id::text"))
      return {rowCount:1,rows:[{actor_id:actor.id}]};
    return {rowCount:1,rows:[]};
  });
});
afterEach(()=>vi.unstubAllEnvs());
describe("private rights ledger controls",()=>{
  it("creates a case with only an allowed type and immutable audit",async()=>{
    const opened=await openRightsCase(actor,"erasure");
    expect(opened).toMatchObject({status:"intake",revision:1});
    expect(fake.query.mock.calls.some(c=>String(c[0])
      .includes("INSERT INTO website_cms.privacy_rights_history"))).toBe(true);
    expect(fake.query.mock.calls.map(c=>c[0])).toContain("COMMIT");
    expect(fake.release).toHaveBeenCalledTimes(1);
  });
  it("rejects unverified or self-approved case transitions",async()=>{
    await expect(advanceRightsCase(actor,caseId,3,"approved","scope_approved"))
      .rejects.toThrow(/Independent/);
    expect(fake.query.mock.calls.map(c=>c[0])).toContain("ROLLBACK");
    expect(fake.query.mock.calls.some(c=>String(c[0])
      .includes("UPDATE website_cms.privacy_rights_cases"))).toBe(false);
  });
  it("blocks sensitive transitions when the prior reviewer is also the current actor",async()=>{
    fake.query.mockImplementation(async(sql:string)=>{
      if(String(sql).includes("FOR UPDATE"))return {rowCount:1,rows:[{
        status:"under_review",revision:3,created_by_actor_id:actor.id,
      }]};
      if(String(sql).includes("SELECT actor_id::text"))
        return {rowCount:1,rows:[{actor_id:reviewer.id}]};
      return {rowCount:1,rows:[]};
    });
    await expect(advanceRightsCase(reviewer,caseId,3,"approved","scope_approved"))
      .rejects.toThrow(/second independent reviewer/);
    expect(fake.query.mock.calls.map(c=>c[0])).toContain("ROLLBACK");
  });
  it("enforces optimistic revision protection before storing history",async()=>{
    await expect(advanceRightsCase(reviewer,caseId,2,"approved","scope_approved"))
      .rejects.toThrow(/revision conflict/);
    expect(fake.query.mock.calls.some(c=>String(c[0])
      .includes("INSERT INTO website_cms.privacy_rights_history"))).toBe(false);
  });
  it("requires an evidence UUID before completion",async()=>{
    await expect(advanceRightsCase(reviewer,caseId,3,"fulfilled",
      "execution_evidence_reviewed")).rejects.toThrow(/Invalid/);
    await expect(advanceRightsCase(reviewer,caseId,3,"denied",
      "policy_exception","not-a-uuid")).rejects.toThrow(/Invalid/);
  });
  it("records an independent approved revision atomically without deleting data",async()=>{
    expect(await advanceRightsCase(reviewer,caseId,3,"approved","scope_approved"))
      .toEqual({id:caseId,revision:4,status:"approved"});
    const commands=fake.query.mock.calls.map(c=>String(c[0]));
    expect(commands.some(x=>x.includes("INSERT INTO website_cms.privacy_rights_history")))
      .toBe(true);
    expect(commands.some(x=>x.includes("DELETE FROM"))).toBe(false);
    expect(commands).toContain("COMMIT");
  });
  it("retrieves a site-scoped history without leaking reviewer or evidence identifiers",async()=>{
    fake.query.mockImplementation(async(sql:string)=>{
      if(String(sql).includes("FROM website_cms.privacy_rights_cases"))
        return {rowCount:1,rows:[{id:caseId}]};
      return {rowCount:1,rows:[{
        revision:2,fromStatus:"intake",toStatus:"verified",
        reasonCode:"identity_confirmed",recordedAt:"2026-10-10T12:00:00Z",
        evidenceLinked:true,
      }]};
    });
    const history=await readRightsCaseHistory(actor,caseId);
    expect(history).toHaveLength(1);
    const statement=String(fake.query.mock.calls[1][0]);
    expect(statement).toContain("site_id=$1 AND case_id=$2");
    expect(statement).not.toContain("actor_id");
    expect(statement).not.toContain("evidence_ref AS");
  });
  it("limits case listing by site and owner permission",async()=>{
    await listRightsCases(actor);
    expect(fake.query.mock.calls[0][1]).toEqual([actor.siteId]);
    await expect(listRightsCases({...actor,permissions:[]}))
      .rejects.toThrow(/permission/);
  });
});
