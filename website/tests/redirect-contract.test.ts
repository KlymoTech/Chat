import {describe,expect,it} from "vitest";
import {isRedirectLookupSource,parseRedirectDraft}
  from "../src/lib/redirect-contract";
const valid={sourcePath:"/content/retired-guide",
  targetPath:"/content/new-guide",reasonCode:"slug_change"};
describe("content redirect allowlist",()=>{
 it("accepts canonical same-origin internal redirects only",()=>{
   expect(parseRedirectDraft(valid)).toEqual(valid);
   expect(parseRedirectDraft({...valid,targetPath:"/services"})).not.toBeNull();
   expect(isRedirectLookupSource("/content/old-guide")).toBe(true);
 });
 it("refuses external, private, script and misleading destination URLs",()=>{
   for(const targetPath of ["https://elsewhere.invalid/","//external.invalid",
     "javascript:alert(1)","/api/owner/pages","/owner/redirects",
     "/content/../private","/content/next?token=secret",
     "/content/next#preview","/content/%2fprivate","/admin"]){
     expect(parseRedirectDraft({...valid,targetPath})).toBeNull();
   }
 });
 it("rejects path impersonation, loops and extraneous attributes",()=>{
   for(const sourcePath of ["/api/users","/content/../admin",
     "/content/old?utm=test","/content/old/child","/content/OLD",
     "/content/%2e%2e","/"]){
     expect(isRedirectLookupSource(sourcePath)).toBe(false);
     expect(parseRedirectDraft({...valid,sourcePath})).toBeNull();
   }
   expect(parseRedirectDraft({...valid,targetPath:valid.sourcePath})).toBeNull();
   expect(parseRedirectDraft({...valid,token:"unsafe"})).toBeNull();
   expect(parseRedirectDraft({...valid,reasonCode:"sales_boost"})).toBeNull();
 });
});
