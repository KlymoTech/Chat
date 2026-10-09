import {describe,expect,it} from "vitest";
import {
  ACTION_PATH,validBuilderSection,validBuilderIdentities,freshBuilderBlock,
} from "../src/lib/builder-contract";
import {isPublishedPage} from "../src/lib/cms";
import {draftFromUnknown} from "../src/lib/owner-api";
const a="550e8400-e29b-41d4-a716-446655440000";
const b="62a2a2bf-1b2a-4fe2-a333-12b2a2a2a2a2";
const page={id:a,path:"/content/good",locale:"en",revision:1,
  title:"Safe published page",description:"",blocks:[]};
describe("owner visual builder contract",()=>{
  it("provides stable identities and accessible editable section defaults",()=>{
    const hero=freshBuilderBlock("hero",a);
    const cta=freshBuilderBlock("cta",b);
    expect(hero.blockId).toBe(a);
    expect(validBuilderSection(hero)).toBe(true);
    expect(validBuilderSection(cta)).toBe(true);
    expect(isPublishedPage({...page,blocks:[hero,cta]})).toBe(true);
  });
  it("accepts accessible FAQ answers but refuses unknown executable embeds",()=>{
    const faq=freshBuilderBlock("faq",a);
    expect(isPublishedPage({...page,blocks:[faq]})).toBe(true);
    expect(isPublishedPage({...page,blocks:[{type:"html",src:"https://evil.test/"}]})).toBe(false);
    expect(validBuilderSection({...faq,items:[]})).toBe(false);
    expect(validBuilderSection({...faq,items:[{question:"",answer:"Text"}]})).toBe(false);
  });
  it("enforces safe fixed internal CTA destinations",()=>{
    expect(ACTION_PATH.test("/contact")).toBe(true);
    expect(ACTION_PATH.test("/content/approved-page")).toBe(true);
    for(const href of ["https://host.invalid/","javascript:alert(1)",
      "/api/owner/pages","//outside.invalid","/content/../owner"]){
      expect(ACTION_PATH.test(href)).toBe(false);
      expect(validBuilderSection({...freshBuilderBlock("cta",a),actionPath:href})).toBe(false);
    }
  });
  it("prevents duplicate stable block IDs independent of ordering",()=>{
    const blocks=[freshBuilderBlock("faq",a),freshBuilderBlock("cta",b)];
    expect(validBuilderIdentities(blocks)).toBe(true);
    expect(validBuilderIdentities([...blocks,{...blocks[0],blockId:b}])).toBe(false);
    expect(validBuilderIdentities([...blocks].reverse())).toBe(true);
  });
  it("preserves compatibility with old immutable text-only revisions",()=>{
    const old=[{type:"paragraph",text:"Legacy section"}];
    expect(isPublishedPage({...page,blocks:old})).toBe(true);
    expect(draftFromUnknown({title:"Legacy",description:"",blocks:old})).not.toBeNull();
  });
  it("rejects malformed visual drafts before save",()=>{
    const cta=freshBuilderBlock("cta",a);
    expect(draftFromUnknown({title:"Safe",description:"",blocks:[cta]})).not.toBeNull();
    expect(draftFromUnknown({title:"Unsafe",description:"",blocks:[
      {...cta,actionPath:"https://malware.invalid"}
    ]})).toBeNull();
  });
});
