import {describe,expect,it} from "vitest";
import {instantiateTemplate,BUILDER_TEMPLATES,isBuilderTemplateId}
  from "../src/lib/builder-templates";
import {isPublishedPage} from "../src/lib/cms";
import {validBuilderIdentities} from "../src/lib/builder-contract";

describe("reusable visual page layouts",()=>{
  let seq=0;
  const uuid=()=>{
    seq++;
    return "550e8400-e29b-41d4-a716-"+seq.toString(16).padStart(12,"0");
  };
  it("has a stable allowlist, no remote or executable templates",()=>{
    expect(BUILDER_TEMPLATES).toHaveLength(3);
    expect(isBuilderTemplateId("services-overview")).toBe(true);
    expect(isBuilderTemplateId("javascript:alert(1)")).toBe(false);
  });
  it("creates new independent identities for each insertion",()=>{
    const first=instantiateTemplate("services-overview",uuid);
    const second=instantiateTemplate("services-overview",uuid);
    expect(validBuilderIdentities([...first,...second])).toBe(true);
    expect(first[0].blockId).not.toBe(second[0].blockId);
  });
  it("renders through the existing safe public CMS contract",()=>{
    for(const template of BUILDER_TEMPLATES){
      const blocks=instantiateTemplate(template.id,uuid);
      const published={
        id:"550e8400-e29b-41d4-a716-446655440000",path:"/content/template",
        locale:"en",revision:1,title:"Test template",description:"",blocks,
      };
      expect(isPublishedPage(published)).toBe(true);
      expect(blocks.some(b=>b.type==="html" as string)).toBe(false);
    }
  });
});
