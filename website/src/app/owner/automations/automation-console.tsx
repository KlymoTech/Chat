"use client";
import {useEffect,useState} from "react";
import Link from "next/link";
import {simulateAutomation,validateAutomation,type AutomationDefinition,type AutomationNode}
  from "../../../lib/automation-contract";

type Summary={id:string;title:string;version:number;updatedAt:string};
const starter:AutomationDefinition={title:"New internal lead review workflow",nodes:[
  {id:"start",type:"trigger",event:"lead_accepted",next:"review"},
  {id:"review",type:"task",action:"review_lead",next:"finish"},
  {id:"finish",type:"exit"},
]};
async function api(path:string,method:"GET"|"POST"="GET",body?:unknown):Promise<unknown>{
  const r=await fetch(path,{method,cache:"no-store",credentials:"same-origin",
    ...(method==="POST"?{headers:{"Content-Type":"application/json"},
      body:JSON.stringify(body)}:{})});
  const result:unknown=await r.json();
  if(!r.ok)throw new Error(result&&typeof result==="object"&&"error" in result&&
    typeof result.error==="string"?result.error:"Automation request unavailable");
  return result;
}
export default function AutomationConsole(){
  const [graph,setGraph]=useState<AutomationDefinition>(starter);
  const [drafts,setDrafts]=useState<Summary[]>([]);
  const [activeId,setActiveId]=useState("");
  const [version,setVersion]=useState(0);
  const [source,setSource]=useState<"form"|"subscription">("form");
  const [consent,setConsent]=useState(false);
  const [clock,setClock]=useState("2026-10-10T09:00");
  const [message,setMessage]=useState("");
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  const [loaded,setLoaded]=useState(false);
  async function refresh(){
    try {
      const data=await api("/api/owner/automations") as {drafts?:Summary[]};
      if(!Array.isArray(data.drafts))throw new Error("Unexpected draft listing");
      setDrafts(data.drafts);setLoaded(true);
    }catch(err){setError(err instanceof Error?err.message:"Drafts unavailable");}
  }
  useEffect(()=>{void refresh();},[]);
  function updateNode(id:string,change:Partial<AutomationNode>){
    setGraph(old=>({...old,nodes:old.nodes.map(node=>
      node.id===id?{...node,...change} as AutomationNode:node)}));
  }
  function addNode(type:"condition"|"delay"|"task"){
    setGraph(old=>{
      if(old.nodes.length>=30)return old;
      const anchor=old.nodes.find(n=>n.type==="trigger");
      if(!anchor)return old;
      const id="node_"+crypto.randomUUID().replaceAll("-","").slice(0,12);
      const next=anchor.next;
      const newNode:AutomationNode=type==="condition"?
        {id,type,field:"marketing_consent",equals:"true",onTrue:next,onFalse:next}:
        type==="delay"?{id,type,minutes:60,next}:
          {id,type,action:"review_lead",next};
      return {...old,nodes:old.nodes.map(node=>node.id===anchor.id?
        {...node,next:id}:node).concat(newNode)};
    });
  }
  async function choose(id:string){
    if(!id){setActiveId("");setVersion(0);setGraph(starter);return;}
    setBusy(true);setError("");setMessage("");
    try{
      const result=await api("/api/owner/automations/"+encodeURIComponent(id)) as {
        id:string;version:number;definition:AutomationDefinition;
      };
      if(!validateAutomation(result.definition))throw new Error("Stored graph invalid");
      setActiveId(id);setVersion(result.version);setGraph(result.definition);
    }catch(err){setError(err instanceof Error?err.message:"Cannot load draft");}
    finally{setBusy(false);}
  }
  async function save(){
    if(busy)return;
    const value=validateAutomation(graph);
    if(!value){setError("The graph needs one trigger, reachable exit paths and valid node destinations.");return;}
    setBusy(true);setError("");setMessage("");
    try{
      const result=activeId?
        await api("/api/owner/automations/"+encodeURIComponent(activeId),"POST",
          {expectedVersion:version,definition:value}):
        await api("/api/owner/automations","POST",value);
      if(!result||typeof result!=="object"||!("id" in result)||!("version" in result))
        throw new Error("Unexpected draft receipt");
      setActiveId(String(result.id));setVersion(Number(result.version));
      setMessage("Immutable draft saved. No workflow was published or executed.");
      await refresh();
    }catch(err){setError(err instanceof Error?err.message:"Unable to save workflow");}
    finally{setBusy(false);}
  }
  const valid=validateAutomation(graph);
  const steps=valid?simulateAutomation(valid,{sourceCategory:source,
    marketingConsent:consent,at:new Date(clock).toISOString?.()??clock}):null;
  return <section className="page" style={{maxWidth:1100}} aria-labelledby="automation-title">
    <p className="eyebrow">Owner workspace · safe draft only</p>
    <h1 id="automation-title">Visual marketing workflows</h1>
    <p className="lead">Create and simulate internal workflow decisions. External messages,
      CRM integrations, live enrollment and customer dispatch are deliberately disabled.</p>
    <p><Link href="/owner">Owner CMS</Link></p>
    {error&&<p role="alert">{error}</p>}
    {message&&<p role="status">{message}</p>}
    <div style={{display:"grid",gap:16}}>
      <label>Saved workflow drafts
        <select value={activeId} disabled={busy} onChange={e=>void choose(e.target.value)}>
          <option value="">New workflow draft</option>
          {drafts.map(d=><option key={d.id} value={d.id}>{d.title} · v{d.version}</option>)}
        </select>
      </label>
      <label>Workflow name
        <input value={graph.title} maxLength={120}
          onChange={e=>setGraph(g=>({...g,title:e.target.value}))}/>
      </label>
      <p>Version: {version||"unsaved"} · status: draft · live execution: disabled</p>
      <div className="owner-actions">
        <button className="button secondary" onClick={()=>addNode("condition")}>Add condition</button>
        <button className="button secondary" onClick={()=>addNode("delay")}>Add delay</button>
        <button className="button secondary" onClick={()=>addNode("task")}>Add internal task</button>
      </div>
      <div role="list" aria-label="Workflow nodes" style={{display:"grid",gap:12}}>
        {graph.nodes.map(node=><section role="listitem" key={node.id}
          style={{background:"#fff",padding:16,border:"1px solid #ccd7db",borderRadius:12}}>
          <h2 style={{fontSize:"1.15rem"}}>{node.type.toUpperCase()} · {node.id}</h2>
          {node.type==="trigger"&&<label>Trusted trigger
            <select value={node.event} onChange={e=>updateNode(node.id,{
              event:e.target.value as "lead_accepted"|"subscription_confirmed",
            })}><option value="lead_accepted">Accepted lead (trusted server event)</option>
              <option value="subscription_confirmed">Verified subscription</option></select>
          </label>}
          {node.type==="condition"&&<>
            <label>Condition field
              <select value={node.field} onChange={e=>updateNode(node.id,{
                field:e.target.value as "marketing_consent"|"source_category",
                equals:e.target.value==="source_category"?"form":"true",
              })}><option value="marketing_consent">Marketing permission</option>
                <option value="source_category">Source category</option></select></label>
            <label>Equals
              <select value={node.equals} onChange={e=>updateNode(node.id,{
                equals:e.target.value as "true",
              })}>{(node.field==="marketing_consent"?["true","false"]:["form","subscription"])
                .map(v=><option key={v}>{v}</option>)}</select></label>
          </>}
          {node.type==="delay"&&<label>Wait minutes (1 to 10080)
            <input type="number" min={1} max={10080} value={node.minutes}
              onChange={e=>updateNode(node.id,{minutes:Number(e.target.value)})}/></label>}
          {node.type==="task"&&<label>Internal-only action
            <select value={node.action} onChange={e=>updateNode(node.id,{
              action:e.target.value as "review_lead"|"notify_owner",
            })}><option value="review_lead">Create internal review task</option>
              <option value="notify_owner">Queue internal owner notification (simulation only)</option></select>
          </label>}
          {node.type!=="exit"&&<p>Next: {node.type==="condition"?
            node.onTrue+" (true) / "+node.onFalse+" (false)":node.next}</p>}
          {node.type==="exit"&&<p>Workflow ends. No external effects.</p>}
        </section>)}
      </div>
      <button className="button" disabled={busy||!valid} onClick={()=>void save()}>
        Save immutable draft version</button>
      <section aria-labelledby="simulation-title">
        <h2 id="simulation-title">Dry-run simulation</h2>
        <p>Uses synthetic data and a virtual clock; no production destinations are contacted.</p>
        <label>Source category<select value={source} onChange={e=>setSource(e.target.value as "form"|"subscription")}>
          <option value="form">Form</option><option value="subscription">Subscription</option></select></label>
        <label><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/>
          Synthetic marketing permission</label>
        <label>Virtual start time<input type="datetime-local" value={clock}
          onChange={e=>setClock(e.target.value)}/></label>
        {steps?<ol>{steps.map((step,i)=><li key={i}>
          {step.at} · {step.nodeId} ({step.type}) {step.decision??""}
        </li>)}</ol>:<p role="alert">Resolve missing paths or invalid simulation inputs.</p>}
      </section>
    </div>
  </section>;
}
