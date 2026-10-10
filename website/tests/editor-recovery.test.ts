import {describe,expect,it} from "vitest";
import type {PublicBlock} from "../src/lib/cms";
import {createRecovery,parseRecovery,recoveryStorageKey,RECOVERY_TTL_MS}
  from "../src/lib/editor-recovery";
const ownerId="550e8400-e29b-41d4-a716-446655440000";
const siteId="62a2a2bf-1b2a-4fe2-a333-12b2a2a2a2a2";
const pageId="e6a94037-1088-4898-b2f8-72f05a4b93aa";
const otherId="f06035b4-90b6-42f3-b77a-41bf024feac0";
const scope={ownerId,siteId,pageId};
const document:{title:string;description:string;blocks:PublicBlock[]}={title:"Unpublished draft",description:"",
  blocks:[{type:"paragraph",text:"Draft content"}]};
const at=1_800_000_000_000;
describe("opt-in browser tab recovery",()=>{
  it("encodes and restores safe drafts for only the same authenticated scope",()=>{
    const raw=createRecovery({...scope,expectedVersion:3,document},at);
    expect(raw).not.toBeNull();
    expect(parseRecovery(raw,scope,at+1000)?.document).toEqual(document);
    expect(recoveryStorageKey(siteId,ownerId,pageId))
      .not.toBe(recoveryStorageKey(siteId,ownerId,otherId));
    expect(parseRecovery(raw,{...scope,ownerId:otherId},at+1000)).toBeNull();
    expect(parseRecovery(raw,{...scope,siteId:otherId},at+1000)).toBeNull();
    expect(parseRecovery(raw,{...scope,pageId:otherId},at+1000)).toBeNull();
  });
  it("expires on exact 2h boundary and rejects future timestamps",()=>{
    const raw=createRecovery({...scope,expectedVersion:2,document},at);
    expect(parseRecovery(raw,scope,at+RECOVERY_TTL_MS-1)).not.toBeNull();
    expect(parseRecovery(raw,scope,at+RECOVERY_TTL_MS)).toBeNull();
    expect(parseRecovery(raw,scope,at-1)).toBeNull();
  });
  it("refuses unknown block types, script-like blocks, and duplicate identities",()=>{
    const a="ca9935e4-5959-4ca5-b9f5-a96202305f1c";
    const base={type:"heading",text:"Safe",blockId:a};
    for(const blocks of [[{type:"html",html:"<script>alert(1)</script>"}],
      [base,{...base}],[{...base,text:"x".repeat(5001)}]]) {
      expect(createRecovery({...scope,expectedVersion:1,
        document:{...document,blocks:blocks as unknown as PublicBlock[]}},at)).toBeNull();
    }
  });
  it("refuses oversized snapshots and malformed schema revisions",()=>{
    expect(createRecovery({...scope,expectedVersion:1,
      document:{...document,title:"x".repeat(181)}},at)).toBeNull();
    expect(createRecovery({...scope,expectedVersion:-1,document},at)).toBeNull();
    const raw=createRecovery({...scope,expectedVersion:1,document},at)!;
    expect(parseRecovery(raw.replace('"version":1','"version":2'),scope,at)).toBeNull();
    expect(parseRecovery("bad json",scope,at)).toBeNull();
    expect(parseRecovery("x".repeat(100001),scope,at)).toBeNull();
  });
});
