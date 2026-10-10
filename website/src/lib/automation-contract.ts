/** Safe internal-only workflow graph. No provider URLs, SQL, JS or messages. */
export type AutomationNode=
 | {id:string;type:"trigger";event:"lead_accepted"|"subscription_confirmed";next:string}
 | {id:string;type:"condition";field:"marketing_consent"|"source_category";
    equals:"true"|"false"|"form"|"subscription";onTrue:string;onFalse:string}
 | {id:string;type:"delay";minutes:number;next:string}
 | {id:string;type:"task";action:"review_lead"|"notify_owner";next:string}
 | {id:string;type:"exit"};
export type AutomationDefinition={title:string;nodes:AutomationNode[]};
const key=/^[a-z][a-z0-9_-]{0,39}$/;
const own=(v:unknown):v is Record<string,unknown>=>
  !!v&&typeof v==="object"&&!Array.isArray(v);
export function validateAutomation(value:unknown):AutomationDefinition|null {
  if(!own(value)||typeof value.title!=="string"||!value.title.trim()||
     value.title.length>120||!Array.isArray(value.nodes)||
     value.nodes.length<2||value.nodes.length>30 ||
     JSON.stringify(value).length>15000)return null;
  const ids=new Set<string>(),nodes:AutomationNode[]=[];
  for(const n of value.nodes){
    if(!own(n)||typeof n.id!=="string"||!key.test(n.id)||ids.has(n.id))return null;
    ids.add(n.id);
    switch(n.type){
      case "trigger":
        if(n.event!=="lead_accepted"&&n.event!=="subscription_confirmed"||
           typeof n.next!=="string")return null;
        nodes.push({id:n.id,type:"trigger",event:n.event,next:n.next});break;
      case "condition":
        if((n.field!=="marketing_consent"&&n.field!=="source_category")||
           !["true","false","form","subscription"].includes(String(n.equals))||
           n.field==="marketing_consent"&&!["true","false"].includes(String(n.equals))||
           n.field==="source_category"&&!["form","subscription"].includes(String(n.equals))||
           typeof n.onTrue!=="string"||typeof n.onFalse!=="string")return null;
        nodes.push({id:n.id,type:"condition",field:n.field,
          equals:n.equals as "true",onTrue:n.onTrue,onFalse:n.onFalse});break;
      case "delay":
        if(!Number.isSafeInteger(n.minutes)||(n.minutes as number)<1||
           (n.minutes as number)>10080||typeof n.next!=="string")return null;
        nodes.push({id:n.id,type:"delay",minutes:n.minutes as number,next:n.next});break;
      case "task":
        if(n.action!=="review_lead"&&n.action!=="notify_owner"||
           typeof n.next!=="string")return null;
        nodes.push({id:n.id,type:"task",action:n.action,next:n.next});break;
      case "exit":nodes.push({id:n.id,type:"exit"});break;
      default:return null;
    }
  }
  const triggers=nodes.filter(n=>n.type==="trigger");
  if(triggers.length!==1||nodes.filter(n=>n.type==="exit").length<1)return null;
  const map=new Map(nodes.map(n=>[n.id,n]));
  const visiting=new Set<string>(),visited=new Set<string>();
  function visit(id:string):boolean {
    if(visiting.has(id))return false;
    if(visited.has(id))return true;
    const node=map.get(id);
    if(!node)return false;
    visiting.add(id);
    const next=node.type==="exit"?[]:node.type==="condition"?
      [node.onTrue,node.onFalse]:[node.next];
    const success=next.every(child=>visit(child));
    visiting.delete(id);visited.add(id);
    return success;
  }
  if(!visit(triggers[0].id)||visited.size!==nodes.length)return null;
  // Every path must reach an exit, not just an arbitrary end.
  return {title:value.title.trim(),nodes};
}
export type SimulatedStep={nodeId:string;type:string;at:string;decision?:string};
export function simulateAutomation(value:unknown,fixture:{
  sourceCategory:"form"|"subscription";marketingConsent:boolean;
  at:string;
}):SimulatedStep[]|null {
  const workflow=validateAutomation(value);
  if(!workflow)return null;
  const instant=Date.parse(fixture.at);
  if(!Number.isFinite(instant)||!["form","subscription"].includes(fixture.sourceCategory)||
     typeof fixture.marketingConsent!=="boolean")return null;
  const map=new Map(workflow.nodes.map(n=>[n.id,n]));
  let next=workflow.nodes.find(n=>n.type==="trigger")!.id;
  let at=instant;
  const steps:SimulatedStep[]=[];
  for(let count=0;count<workflow.nodes.length;count++){
    const node=map.get(next);
    if(!node)return null;
    if(node.type==="condition"){
      const actual=node.field==="marketing_consent"?
        String(fixture.marketingConsent):fixture.sourceCategory;
      const yes=actual===node.equals;
      steps.push({nodeId:node.id,type:node.type,at:new Date(at).toISOString(),
        decision:yes?"true":"false"});
      next=yes?node.onTrue:node.onFalse;
    }else if(node.type==="delay"){
      at+=node.minutes*60000;
      steps.push({nodeId:node.id,type:node.type,at:new Date(at).toISOString()});
      next=node.next;
    }else{
      steps.push({nodeId:node.id,type:node.type,at:new Date(at).toISOString()});
      if(node.type==="exit")return steps;
      next=node.next;
    }
  }
  return null;
}
