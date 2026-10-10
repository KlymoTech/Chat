import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
vi.mock("server-only",()=>({}));
const fake=vi.hoisted(()=>({query:vi.fn(),release:vi.fn(),connect:vi.fn()}));
vi.mock("pg",()=>({Pool:class{
 connect(){return fake.connect();}
 query(...args:unknown[]){return fake.query(...args);}
}}));
import {reviewRedirect,lookupPublicContentRedirect}
  from "../src/lib/content-redirects";
import type {CmsActor} from "../src/lib/cms-editor";
const actor:CmsActor={
 id:"550e8400-e29b-41d4-a716-446655440000",
 siteId:"62a2a2bf-1b2a-4fe2-a333-12b2a2a2a2a2",
 permissions:["cms:redirect"],
};
const reviewer:CmsActor={...actor,id:"e6a94037-1088-4898-b2f8-72f05a4b93aa"};
const id="f06035b4-90b6-42f3-b77a-41bf024feac0";
function response(sql:string){
 if(sql.includes("SELECT source_path"))return {rowCount:1,rows:[{
   source_path:"/content/old-guide",target_path:"/content/new-guide",
   status:"draft",requested_by:actor.id,
 }]};
 if(sql.includes("JOIN website_cms.page_revisions"))return {rowCount:1,rows:[{id:"ok"}]};
 if(sql.includes("FROM website_cms.sites"))return {rowCount:1,rows:[{id:actor.siteId}]};
 if(sql.includes("FROM website_cms.pages")||sql.includes("FROM website_cms.content_redirects"))
   return {rowCount:0,rows:[]};
 return {rowCount:1,rows:[]};
}
beforeEach(()=>{
 vi.stubEnv("WEBSITE_REDIRECT_EDITOR_ENABLED","true");
 vi.stubEnv("WEBSITE_REDIRECT_EDITOR_GRANTS_VERIFIED","true");
 vi.stubEnv("WEBSITE_REDIRECT_EDITOR_DATABASE_URL","postgres://local/test");
 vi.stubEnv("WEBSITE_REDIRECT_PUBLIC_ENABLED","false");
 fake.query.mockReset();fake.release.mockReset();
 fake.connect.mockReset().mockResolvedValue({
  query:fake.query,release:fake.release,
 });
 fake.query.mockImplementation(async(sql:string)=>response(sql));
});
afterEach(()=>vi.unstubAllEnvs());
describe("dual-controlled SEO content redirects",()=>{
 it("refuses self approval and writes no audit or public state",async()=>{
   await expect(reviewRedirect(actor,id,"approve")).rejects.toThrow(/Independent/);
   expect(fake.query.mock.calls.map(c=>String(c[0]))).toContain("ROLLBACK");
   expect(fake.query.mock.calls.some(c=>String(c[0])
     .includes("UPDATE website_cms.content_redirects"))).toBe(false);
 });
 it("checks site, route occupancy, redirect chains and published targets",async()=>{
   expect(await reviewRedirect(reviewer,id,"approve")).toEqual({
     id,status:"approved",
   });
   const commands=fake.query.mock.calls.map(c=>String(c[0]));
   expect(commands.some(x=>x.includes("BEGIN ISOLATION LEVEL SERIALIZABLE"))).toBe(true);
   expect(commands.some(x=>x.includes("p.current_published_revision_id"))).toBe(true);
   expect(commands.some(x=>x.includes("cms.redirect_approved"))).toBe(true);
   expect(commands).toContain("COMMIT");
 });
 it("rejects chains even when the requested target is otherwise valid",async()=>{
   fake.query.mockImplementation(async(sql:string)=>{
     if(String(sql).includes("AND (source_path=$2 OR target_path=$3)"))
       return {rowCount:1,rows:[{id:"previous-redirect"}]};
     return response(sql);
   });
   await expect(reviewRedirect(reviewer,id,"approve"))
     .rejects.toThrow(/chains and loops/);
   expect(fake.query.mock.calls.map(c=>String(c[0]))).toContain("ROLLBACK");
   expect(fake.query.mock.calls.some(c=>String(c[0])
     .includes("SET status='approved'"))).toBe(false);
 });
 it("rejects a missing published destination and rolls back",async()=>{
   fake.query.mockImplementation(async(sql:string)=>
     sql.includes("JOIN website_cms.page_revisions")?
       {rowCount:0,rows:[]}:response(sql));
   await expect(reviewRedirect(reviewer,id,"approve"))
     .rejects.toThrow(/destination is not published/);
   expect(fake.query.mock.calls.map(c=>String(c[0]))).toContain("ROLLBACK");
 });
 it("suppresses public redirects until both explicit release gates are enabled",async()=>{
   expect(await lookupPublicContentRedirect("/content/old-guide")).toBeNull();
   expect(fake.query.mock.calls.some(c=>String(c[0])
     .includes("public_approved_content_redirects"))).toBe(false);
 });
});
