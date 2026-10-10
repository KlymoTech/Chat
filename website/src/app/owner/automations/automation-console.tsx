"use client";
import {useEffect,useState} from "react";
import Link from "next/link";
import {simulateAutomation,validateAutomation,type AutomationDefinition,type AutomationNode}
  from "../../../lib/automation-contract";

type Summary={id:string;title:string;version:number;updatedAt:string};
type StoredRun={id:string;status:string;currentNodeId:string;dueAt:string;processedSteps:number};
type InternalTask={id:string;runId:string;nodeId:string;action:string;state:string;createdAt:string};
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
  const [acknowledgedGraph,setAcknowledgedGraph]=useState(JSON.stringify(starter));
  const [drafts,setDrafts]=useState<Summary[]>([]);
  const [runs,setRuns]=useState<StoredRun[]>([]);
  const [tasks,setTasks]=useState<InternalTask[]>([]);
  const [taskReasons,setTaskReasons]=useState<Record<string,string>>({});
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
  async function loadRuns(id:string){
    if(!id){setRuns([]);return;}
    try{
      const result=await api("/api/owner/automations/"+encodeURIComponent(id)+"/runs") as {runs?:StoredRun[]};
      if(Array.isArray(result.runs))setRuns(result.runs);
    }catch{setRuns([]);}
  }
  async function loadTasks(id:string){
    if(!id){setTasks([]);return;}
    try{
      const result=await api("/api/owner/automations/"+encodeURIComponent(id)+"/tasks") as {tasks?:InternalTask[]};
      if(Array.isArray(result.tasks))setTasks(result.tasks);
    }catch{setTasks([]);}
  }
  async function completeTask(taskId:string){
    if(!activeId||busy)return;
    const reason=taskReasons[taskId]?.trim()??"";
    if(reason.length<10||reason.length>500)return;
    setBusy(true);setError("");setMessage("");
    try{
      await api("/api/owner/automations/"+encodeURIComponent(activeId)+"/tasks",
        "POST",{taskId,reason});
      setMessage("Internal synthetic task marked done with an audit reason.");
      await loadTasks(activeId);
    }catch(err){setError(err instanceof Error?err.message:"Unable to complete task");}
    finally{setBusy(false);}
  }
  async function choose(id:string){
    if(!id){setActiveId("");setVersion(0);setGraph(starter);
      setAcknowledgedGraph(JSON.stringify(starter));setRuns([]);setTasks([]);return;}
    setBusy(true);setError("");setMessage("");
    try{
      const result=await api("/api/owner/automations/"+encodeURIComponent(id)) as {
        id:string;version:number;definition:AutomationDefinition;
      };
      if(!validateAutomation(result.definition))throw new Error("Stored graph invalid");
      setActiveId(id);setVersion(result.version);setGraph(result.definition);
      setAcknowledgedGraph(JSON.stringify(result.definition));
      await Promise.all([loadRuns(id),loadTasks(id)]);
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
      setAcknowledgedGraph(JSON.stringify(value));
      await Promise.all([loadRuns(String(result.id)),loadTasks(String(result.id))]);
      setMessage("Immutable draft saved. No workflow was published or executed.");
      await refresh();
    }catch(err){setError(err instanceof Error?err.message:"Unable to save workflow");}
    finally{setBusy(false);}
  }
  async function queueSyntheticRun(){
    if(!activeId||busy)return;
    setBusy(true);setError("");setMessage("");
    try{
      const result=await api("/api/owner/automations/"+encodeURIComponent(activeId)+"/test-run",
        "POST",{sourceCategory:source,marketingConsent:consent});
      if(!result||typeof result!=="object"||!("runId" in result))
        throw new Error("Synthetic test was not confirmed");
      setMessage("Synthetic run accepted. Use a signed internal runner to advance due nodes.");
      await Promise.all([loadRuns(activeId),loadTasks(activeId)]);
    }catch(e){setError(e instanceof Error?e.message:"Synthetic run unavailable");}
    finally{setBusy(false);}
  }
  const valid=validateAutomation(graph);
  const graphHasUnsavedChanges=JSON.stringify(graph)!==acknowledgedGraph;
  const steps=valid?simulateAutomation(valid,{sourceCategory:source,
    marketingConsent:consent,at:Number.isFinite(Date.parse(clock))?
      new Date(clock).toISOString():"invalid"}):null;
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
      <p role="status">Version: {version||"unsaved"} · status: draft · live execution: disabled · {graphHasUnsavedChanges?"Unsaved graph edits":"Server-acknowledged graph"}</p>
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
          {node.type==="condition"?<>
            <label>True branch
              <select value={node.onTrue} onChange={e=>updateNode(node.id,{onTrue:e.target.value})}>
                {graph.nodes.filter(n=>n.id!==node.id).map(n=><option key={n.id} value={n.id}>{n.id}</option>)}
              </select></label>
            <label>False branch
              <select value={node.onFalse} onChange={e=>updateNode(node.id,{onFalse:e.target.value})}>
                {graph.nodes.filter(n=>n.id!==node.id).map(n=><option key={n.id} value={n.id}>{n.id}</option>)}
              </select></label>
          </>:node.type!=="exit"?<label>Next node
            <select value={node.next} onChange={e=>updateNode(node.id,{next:e.target.value})}>
              {graph.nodes.filter(n=>n.id!==node.id).map(n=><option key={n.id} value={n.id}>{n.id}</option>)}
            </select></label>:null}
          {node.type==="exit"&&<p>Workflow ends. No external effects.</p>}
        </section>)}
      </div>
      <button className="button" disabled={busy||!valid} onClick={()=>void save()}>
        Save immutable draft version</button>
      <section aria-labelledby="synthetic-title">
        <h2 id="synthetic-title">Durable synthetic test runs</h2>
        <p>No real contacts, messages, payments or CRM actions are enrolled.
          A separate authenticated internal runner advances due nodes and stores internal tasks.
          All processing remains disabled until the operator enables staging verification.</p>
        <button className="button secondary" type="button"
          disabled={busy||!activeId||!valid||graphHasUnsavedChanges} onClick={()=>void queueSyntheticRun()}>
          Enqueue synthetic workflow run</button>
        <button className="button secondary" type="button"
          disabled={busy||!activeId} onClick={()=>void Promise.all([loadRuns(activeId),loadTasks(activeId)])}>
          Refresh run statuses and tasks</button>
        {tasks.length>0&&<section aria-labelledby="internal-tasks-title">
          <h3 id="internal-tasks-title">Pending and completed internal tasks</h3>
          {tasks.map(task=><div key={task.id} style={{margin:"1rem 0",padding:12,
            border:"1px solid #ccd7db",borderRadius:8}}>
            <p><strong>{task.action.replaceAll("_"," ")}</strong> · {task.state} · run {task.runId.slice(0,8)}</p>
            {task.state==="pending"&&<>
              <label>Completion justification (10–500 characters)
                <textarea rows={2} maxLength={500} value={taskReasons[task.id]??""}
                  onChange={event=>setTaskReasons(old=>({...old,[task.id]:event.target.value}))}/>
              </label>
              <button className="button secondary" type="button"
                disabled={busy||(taskReasons[task.id]?.trim().length??0)<10}
                onClick={()=>void completeTask(task.id)}>Mark internal task done</button>
            </>}
          </div>)}
        </section>}
        {runs.length>0?<table>
          <thead><tr><th scope="col">Run</th><th scope="col">Status</th>
            <th scope="col">Next node</th><th scope="col">Steps</th></tr></thead>
          <tbody>{runs.map(run=><tr key={run.id}>
            <td>{run.id.slice(0,8)}</td><td>{run.status}</td>
            <td>{run.currentNodeId}</td><td>{run.processedSteps}</td>
          </tr>)}</tbody>
        </table>:<p>No synthetic runs loaded.</p>}
      </section>
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
