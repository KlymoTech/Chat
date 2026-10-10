import {describe,expect,it} from "vitest";
import {planInternalAutomationStep} from "../src/lib/internal-automation-engine";
const graph={title:"Internal lead review only",nodes:[
 {id:"start",type:"trigger",event:"lead_accepted",next:"eligible"},
 {id:"eligible",type:"condition",field:"marketing_consent",equals:"true",
   onTrue:"delay",onFalse:"review"},
 {id:"delay",type:"delay",minutes:60,next:"review"},
 {id:"review",type:"task",action:"review_lead",next:"end"},
 {id:"end",type:"exit"},
]};
const at="2026-10-10T12:00:00.000Z";
const safe={sourceCategory:"form" as const,marketingConsent:false};
describe("durable internal-only workflow transitions",()=>{
  it("follows deny-by-default eligibility through internal review",()=>{
    const start=planInternalAutomationStep(graph,"start",safe,at,0);
    expect(start?.nextNodeId).toBe("eligible");
    const condition=planInternalAutomationStep(graph,"eligible",safe,at,1);
    expect(condition?.nextNodeId).toBe("review");
    const task=planInternalAutomationStep(graph,"review",safe,at,2);
    expect(task).toMatchObject({task:"review_lead",nextNodeId:"end",
      result:"advanced",nextStatus:"running"});
    expect(planInternalAutomationStep(graph,"end",safe,at,3)?.nextStatus)
      .toBe("completed");
  });
  it("durably schedules delay without any external send",()=>{
    const allowed={...safe,marketingConsent:true};
    expect(planInternalAutomationStep(graph,"eligible",allowed,at,1)?.nextNodeId)
      .toBe("delay");
    const wait=planInternalAutomationStep(graph,"delay",allowed,at,2);
    expect(wait).toMatchObject({dueAt:"2026-10-10T13:00:00.000Z",
      nextStatus:"waiting",result:"waiting",task:null});
  });
  it("rejects malformed graphs and exhausted execution budgets",()=>{
    expect(planInternalAutomationStep(graph,"unknown",safe,at,0)).toBeNull();
    expect(planInternalAutomationStep(graph,"start",safe,at,60)).toBeNull();
    expect(planInternalAutomationStep(graph,"start",safe,at,-1)).toBeNull();
    expect(planInternalAutomationStep(graph,"start",safe,"bad",0)).toBeNull();
    expect(planInternalAutomationStep({...graph,nodes:graph.nodes.slice(1)},
      "eligible",safe,at,0)).toBeNull();
  });
});
