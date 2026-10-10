import {describe,expect,it} from "vitest";
import {validateAutomation,simulateAutomation} from "../src/lib/automation-contract";

const valid={title:"Internal lead review",nodes:[
  {id:"start",type:"trigger",event:"lead_accepted",next:"permission"},
  {id:"permission",type:"condition",field:"marketing_consent",equals:"true",
    onTrue:"wait",onFalse:"exit"},
  {id:"wait",type:"delay",minutes:60,next:"review"},
  {id:"review",type:"task",action:"review_lead",next:"exit"},
  {id:"exit",type:"exit"},
]};
describe("versioned automation draft graph",()=>{
  it("accepts typed connected workflows with a safe simulation",()=>{
    expect(validateAutomation(valid)).not.toBeNull();
    const yes=simulateAutomation(valid,{sourceCategory:"form",marketingConsent:true,
      at:"2026-10-10T09:00:00.000Z"});
    expect(yes?.map(step=>step.type)).toEqual([
      "trigger","condition","delay","task","exit",
    ]);
    expect(yes?.find(step=>step.type==="delay")?.at).toBe("2026-10-10T10:00:00.000Z");
    const no=simulateAutomation(valid,{sourceCategory:"form",marketingConsent:false,
      at:"2026-10-10T09:00:00.000Z"});
    expect(no?.map(step=>step.type)).toEqual(["trigger","condition","exit"]);
  });
  it("rejects cycles, missing exits, dangling edges and unreachable nodes",()=>{
    expect(validateAutomation({...valid,nodes:valid.nodes.map(n=>
      n.id==="review"?{...n,next:"start"}:n)})).toBeNull();
    expect(validateAutomation({...valid,nodes:valid.nodes.filter(n=>n.id!=="exit")})).toBeNull();
    expect(validateAutomation({...valid,nodes:[...valid.nodes,{id:"unused",type:"exit"}]})).toBeNull();
    expect(validateAutomation({...valid,nodes:valid.nodes.map(n=>
      n.id==="start"?{...n,next:"missing"}:n)})).toBeNull();
  });
  it("refuses executable actions, arbitrary URLs and unsupported sensitive conditions",()=>{
    expect(validateAutomation({...valid,nodes:valid.nodes.map(n=>n.id==="review"?
      {...n,action:"send_to_external_webhook",url:"https://bad.invalid"}:n)})).toBeNull();
    expect(validateAutomation({...valid,nodes:valid.nodes.map(n=>n.id==="permission"?
      {...n,field:"medical_condition"}:n)})).toBeNull();
    expect(validateAutomation({...valid,nodes:valid.nodes.map(n=>n.id==="wait"?
      {...n,minutes:200000}:n)})).toBeNull();
  });
  it("rejects oversized graphs and malformed IDs",()=>{
    expect(validateAutomation({...valid,nodes:valid.nodes.map(n=>
      n.id==="start"?{...n,id:"<script>"}:n)})).toBeNull();
    expect(validateAutomation({...valid,title:"x".repeat(121)})).toBeNull();
  });
});
