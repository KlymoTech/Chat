"use client";
import {useEffect,useState} from "react";
import Link from "next/link";
import "../../owner.css";
import {
 RIGHT_KINDS,validCaseKind,allowedCaseTransition,CASE_STATES,CASE_REASONS,
 type RightKind,type CaseState,type CaseReason,
} from "../../../../lib/privacy-rights-contract";
type HistoryItem={revision:number;fromStatus:string|null;toStatus:string;reasonCode:string;recordedAt:string;evidenceLinked:boolean};
type RightsCase={
 id:string;requestKind:RightKind;status:CaseState;revision:number;
 createdAt:string;updatedAt:string;
};
async function call(path:string,method:"GET"|"POST",body?:unknown):Promise<unknown>{
  const response=await fetch(path,{method,cache:"no-store",credentials:"same-origin",
    ...(method==="POST"?{headers:{"Content-Type":"application/json"},
      body:JSON.stringify(body)}:{})});
  const json:unknown=await response.json();
  if(!response.ok)throw new Error(
    json&&typeof json==="object"&&"error" in json&&typeof json.error==="string"?
      json.error:"Rights case operation unavailable");
  return json;
}
export default function PrivacyRightsConsole(){
  const [cases,setCases]=useState<RightsCase[]>([]);
  const [kind,setKind]=useState<RightKind>("access");
  const [status,setStatus]=useState("Loading restricted privacy cases…");
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  const [history,setHistory]=useState<Record<string,HistoryItem[]>>({});
  const [decision,setDecision]=useState<Record<string,{to:CaseState;reason:CaseReason;evidenceRef:string}>>({});
  async function refresh(){
    try{
      const data=await call("/api/owner/privacy/rights","GET") as {cases?:RightsCase[]};
      if(!Array.isArray(data.cases))throw Error("Unexpected response");
      setCases(data.cases);
      setStatus("Only opaque case IDs and lifecycle metadata are shown.");
    }catch(e){setError(e instanceof Error?e.message:"Privacy cases unavailable");
      setStatus("Privacy case management is unavailable.");}
  }
  useEffect(()=>{void refresh();},[]);
  async function open(){
    if(busy||!validCaseKind(kind))return;
    setBusy(true);setError("");
    try{
      await call("/api/owner/privacy/rights","POST",{kind});
      setStatus("Opaque case opened. Verify the requester through an approved separate process.");
      await refresh();
    }catch(e){setError(e instanceof Error?e.message:"Cannot open case");}
    finally{setBusy(false);}
  }
  function options(row:RightsCase){
    const choices:{to:CaseState;reason:CaseReason}[]=[];
    for(const to of CASE_STATES){
      for(const reason of CASE_REASONS){
        if(allowedCaseTransition(row.status,to,reason)){
          choices.push({to,reason});break;
        }
      }
    }
    return choices;
  }
  async function loadHistory(id:string){
    try{
      const response=await call("/api/owner/privacy/rights/"+encodeURIComponent(id)+"/history",
        "GET") as {history?:HistoryItem[]};
      if(!Array.isArray(response.history))throw Error("Invalid history response");
      setHistory(old=>({...old,[id]:response.history??[]}));
    }catch(e){setError(e instanceof Error?e.message:"History unavailable");}
  }
  async function submit(row:RightsCase){
    if(busy)return;
    const value=decision[row.id]??options(row)[0];
    if(!value||!allowedCaseTransition(row.status,value.to,value.reason))return;
    setBusy(true);setError("");
    try{
      await call("/api/owner/privacy/rights/"+encodeURIComponent(row.id),"POST",{
        expectedRevision:row.revision,to:value.to,reason:value.reason,
        ...(decision[row.id]?.evidenceRef?{evidenceRef:decision[row.id].evidenceRef}:{}),
      });
      setStatus("Privacy case advanced with an immutable audit entry. No personal data was deleted.");
      await refresh();
    }catch(e){setError(e instanceof Error?e.message:"Review denied");
      await refresh();}
    finally{setBusy(false);}
  }
  return <section className="page" aria-labelledby="rights-title">
    <p className="eyebrow">Private owner operations · disabled until reviewed</p>
    <h1 id="rights-title">Privacy rights case ledger</h1>
    <p>Record and track requests for access, correction, erasure, objection or restriction.
      Identity and legal basis must be verified outside this interface. This system neither
      deletes records nor contacts processors automatically.</p>
    <p><Link href="/owner">Return to owner CMS</Link></p>
    {error&&<p role="alert">{error}</p>}
    <p role="status">{status}</p>
    <div className="owner-actions">
      <label>Type of request
        <select value={kind} onChange={event=>setKind(event.target.value as RightKind)}>
          {RIGHT_KINDS.map(x=><option key={x} value={x}>{x}</option>)}
        </select>
      </label>
      <button className="button" type="button" disabled={busy}
        onClick={()=>void open()}>Open opaque case</button>
      <button className="button secondary" type="button" disabled={busy}
        onClick={()=>void refresh()}>Refresh</button>
    </div>
    {cases.length?<div style={{display:"grid",gap:16,marginTop:24}}>
      {cases.map(row=>{
        const steps=options(row);
        const active=decision[row.id];
        const chosen=steps.find(x=>x.to===active?.to)??steps[0];
        const needsEvidence=chosen&&["verified","denied","fulfilled"].includes(chosen.to);
        return <section key={row.id} aria-label={"Privacy case "+row.id.slice(0,8)}
          style={{padding:16,border:"1px solid #ccd9e0",borderRadius:12}}>
          <h2>{row.requestKind} · {row.id.slice(0,8)}</h2>
          <p>State: <strong>{row.status}</strong> · revision {row.revision}
             · last updated {new Date(row.updatedAt).toLocaleString()}</p>
          <button type="button" className="button secondary"
            onClick={()=>void loadHistory(row.id)}>
            View immutable status history
          </button>
          {history[row.id]&&<ol aria-label="Case status history">
            {history[row.id].map(entry=><li key={entry.revision}>
              <strong>Revision {entry.revision}</strong>: {entry.fromStatus??"opened"}
              {" → "}{entry.toStatus} ({entry.reasonCode.replaceAll("_"," ")})
              {entry.evidenceLinked?" · evidence reference recorded":""}
            </li>)}
          </ol>}
          {steps.length>0?<div style={{display:"grid",gap:8}}>
            <label>Next review decision
              <select value={chosen?.to??""} onChange={e=>{
                const next=steps.find(x=>x.to===e.target.value);
                if(next)setDecision(old=>({...old,[row.id]:{
                  to:next.to,reason:next.reason,
                  evidenceRef:old[row.id]?.evidenceRef??"",
                }}));
              }}>
                {steps.map(x=><option key={x.to} value={x.to}>
                  {x.to.replaceAll("_"," ")}
                </option>)}
              </select>
            </label>
            <p>Controlled reason: {chosen?.reason.replaceAll("_"," ")}</p>
            {needsEvidence&&<label>External evidence reference (UUID only; no documents)
              <input value={active?.evidenceRef??""} maxLength={36}
                placeholder="Approved external case evidence UUID"
                onChange={event=>setDecision(old=>({...old,[row.id]:{
                  to:chosen.to,reason:chosen.reason,evidenceRef:event.target.value,
                }}))}/>
            </label>}
            <button className="button secondary" type="button"
              disabled={busy||!chosen||(needsEvidence&&!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(active?.evidenceRef??""))}
              onClick={()=>void submit({...row})}>
              Submit review transition</button>
          </div>:<p>No permitted further transitions; the case remains auditable.</p>}
        </section>;
      })}
    </div>:<p>No recorded cases, or owner storage is not active.</p>}
  </section>;
}
