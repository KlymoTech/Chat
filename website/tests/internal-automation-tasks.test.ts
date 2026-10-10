import {beforeEach,afterEach,describe,expect,it,vi} from "vitest";
vi.mock("server-only",()=>({}));
const fake=vi.hoisted(()=>({query:vi.fn(),release:vi.fn()}));
vi.mock("pg",()=>({Pool:class{connect(){return Promise.resolve(fake);}
  query(...args:unknown[]){return fake.query(...args);}}}));
import {completeInternalAutomationTask,listInternalAutomationTasks}
  from "../src/lib/internal-automation-runs";
import type {CmsActor} from "../src/lib/cms-editor";
const actor:CmsActor={id:"550e8400-e29b-41d4-a716-446655440000",
 siteId:"62a2a2bf-1b2a-4fe2-a333-12b2a2a2a2a2",
 permissions:["cms:automation"]};
const workflowId="e6a94037-1088-4898-b2f8-72f05a4b93aa";
const taskId="f06035b4-90b6-42f3-b77a-41bf024feac0";
beforeEach(()=>{
  vi.stubEnv("WEBSITE_AUTOMATION_INTERNAL_RUNS_ENABLED","true");
  vi.stubEnv("WEBSITE_AUTOMATION_RUN_DB_ROLE_VERIFIED","true");
  vi.stubEnv("WEBSITE_AUTOMATION_RUN_DATABASE_URL",
    "postgres://role:secret@localhost/website_test");
  fake.query.mockReset();fake.release.mockReset();
  fake.query.mockResolvedValue({rowCount:1,rows:[]});
});
afterEach(()=>vi.unstubAllEnvs());
describe("manual internal task completion",()=>{
  it("site-scopes the pending task UPDATE and commits an audit reason",async()=>{
    expect(await completeInternalAutomationTask(actor,workflowId,taskId,
      "Reviewed synthetic case and resolved internal task")).toEqual({
      id:taskId,state:"done",
    });
    const sql=fake.query.mock.calls.find(c=>String(c[0]).includes(
      "UPDATE website_cms.automation_internal_tasks"));
    expect(sql?.[1]).toEqual([taskId,actor.siteId,workflowId]);
    expect(String(sql?.[0])).toContain("r.subject_type='synthetic'");
    expect(fake.query.mock.calls.some(c=>String(c[0]).includes(
      "INSERT INTO website_cms.audit_events"))).toBe(true);
    expect(fake.query.mock.calls.map(c=>c[0])).toContain("COMMIT");
  });
  it("does not acknowledge missing, previously completed or wrong-tenant tasks",async()=>{
    fake.query.mockImplementation(async(sql:string)=>
      String(sql).includes("UPDATE website_cms.automation_internal_tasks")?
        {rowCount:0,rows:[]}:{rowCount:1,rows:[]});
    await expect(completeInternalAutomationTask(actor,workflowId,taskId,
      "Attempted duplicate decision")).rejects.toThrow(/not pending/);
    expect(fake.query.mock.calls.map(c=>c[0])).toContain("ROLLBACK");
    expect(fake.query.mock.calls.some(c=>String(c[0]).includes(
      "INSERT INTO website_cms.audit_events"))).toBe(false);
  });
  it("requires permission, a reason and exact UUID identities",async()=>{
    await expect(completeInternalAutomationTask({...actor,permissions:[]},
      workflowId,taskId,"Sufficient reason")).rejects.toThrow(/permission/);
    await expect(completeInternalAutomationTask(actor,workflowId,taskId,"no"))
      .rejects.toThrow(/Invalid/);
    await expect(completeInternalAutomationTask(actor,"../../private",taskId,
      "A reason longer than ten characters")).rejects.toThrow(/Invalid/);
  });
  it("does not return tasks belonging to another workflow",async()=>{
    await listInternalAutomationTasks(actor,workflowId);
    const sql=fake.query.mock.calls[0];
    expect(String(sql[0])).toContain("r.definition_id=$2");
    expect(sql[1]).toEqual([actor.siteId,workflowId]);
  });
});
