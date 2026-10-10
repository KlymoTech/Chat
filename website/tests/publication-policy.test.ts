import { describe, expect, it } from "vitest";
import { collectPublicResources } from "../src/lib/publication-policy";

const base = {
  id:"550e8400-e29b-41d4-a716-446655440000",
  path:"/content/article-one", locale:"en", revision:1,
  title:"Verified article", description:"Approved resource description",
  blocks:[{type:"paragraph",text:"Public content"}],
};
describe("public content listing policy",()=>{
  it("accepts a canonical published-view row without leaking body blocks",()=>{
    expect(collectPublicResources([base],"en")).toEqual([{
      path:"/content/article-one",title:"Verified article",
      description:"Approved resource description",
    }]);
  });
  it("excludes malformed routes, wrong locales and arbitrary HTML blocks",()=>{
    const invalid=[
      {...base,path:"/owner"},
      {...base,path:"/content/other/nested"},
      {...base,path:"/content/../private"},
      {...base,locale:"fr"},
      {...base,blocks:[{type:"html",html:"<script>bad()</script>"}]},
      {...base,revision:0},
      {...base,title:"x".repeat(181)},
    ];
    expect(collectPublicResources(invalid,"en")).toEqual([]);
  });
  it("deduplicates repeated public routes and bounds the inspected candidates",()=>{
    const rows=[base,{...base,id:"62a2a2bf-1b2a-4fe2-a333-12b2a2a2a2a2"}];
    expect(collectPublicResources(rows,"en")).toHaveLength(1);
    const later={...base,path:"/content/last-one"};
    expect(collectPublicResources([...Array.from({length:100},(_,i)=>({
      ...base,path:"/content/article-"+i
    })),later],"en")).toHaveLength(100);
  });
  it("fails closed for unexpected locale selectors",()=>{
    expect(collectPublicResources([base],"../en")).toEqual([]);
  });
});
