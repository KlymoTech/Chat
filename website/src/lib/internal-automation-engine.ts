import {validateAutomation,type AutomationDefinition} from "./automation-contract";

export type TrustedInternalContext=Readonly<{
 sourceCategory:"form"|"subscription";
 marketingConsent:boolean;
}>;
export type PlannedInternalStep=Readonly<{
 nodeId:string;result:"advanced"|"waiting"|"completed";
 nextNodeId:string;nextStatus:"running"|"waiting"|"completed";
 dueAt:string;task:"review_lead"|"notify_owner"|null;
}>;
/** Pure deterministic internal transition planner. Not a provider dispatcher. */
export function planInternalAutomationStep(
  definition:unknown,nodeId:string,context:TrustedInternalContext,
  at:string,processedSteps:number,
):PlannedInternalStep|null {
  const workflow:AutomationDefinition|null=validateAutomation(definition);
  if(!workflow||typeof nodeId!=="string"||
     !["form","subscription"].includes(context?.sourceCategory)||
     typeof context.marketingConsent!=="boolean"||
     !Number.isSafeInteger(processedSteps)||processedSteps<0||
     processedSteps>=60)return null;
  const clock=Date.parse(at);
  if(!Number.isFinite(clock))return null;
  const node=workflow.nodes.find(x=>x.id===nodeId);
  if(!node)return null;
  if(node.type==="exit"){
    return {nodeId,result:"completed",nextNodeId:nodeId,nextStatus:"completed",
      dueAt:new Date(clock).toISOString(),task:null};
  }
  if(node.type==="condition"){
    const match=(node.field==="marketing_consent"?
      String(context.marketingConsent):context.sourceCategory)===node.equals;
    return {nodeId,result:"advanced",nextNodeId:match?node.onTrue:node.onFalse,
      nextStatus:"running",dueAt:new Date(clock).toISOString(),task:null};
  }
  if(node.type==="delay"){
    const due=clock+node.minutes*60000;
    if(!Number.isFinite(due))return null;
    return {nodeId,result:"waiting",nextNodeId:node.next,
      nextStatus:"waiting",dueAt:new Date(due).toISOString(),task:null};
  }
  if(node.type==="task"){
    return {nodeId,result:"advanced",nextNodeId:node.next,
      nextStatus:"running",dueAt:new Date(clock).toISOString(),task:node.action};
  }
  return {nodeId,result:"advanced",nextNodeId:node.next,
    nextStatus:"running",dueAt:new Date(clock).toISOString(),task:null};
}
