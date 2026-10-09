"use client";
import {useCallback,useEffect,useState} from "react";
import Link from "next/link";
type Pending={
  id:string;originalFilename:string;state:string;blobStatus:string;
  createdByActorId:string;altDefault:string;rightsStatement:string;
  scanEngine:string|null;scannedAt:string|null;sanitizedSha256:string|null;
};
async function load(url:string,body?:unknown):Promise<unknown>{
  const response=await fetch(url,{
    method:body?"POST":"GET",cache:"no-store",credentials:"same-origin",
    ...(body?{headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}:{}),
  });
  const json:unknown=await response.json();
  if(!response.ok){
    const msg=json&&typeof json==="object"&&"error" in json&&typeof json.error==="string"
      ?json.error:"Private media review unavailable";
    throw new Error(msg);
  }
  return json;
}
export default function MediaReviewConsole(){
  const [items,setItems]=useState<Pending[]>([]);
  const [reasons,setReasons]=useState<Record<string,string>>({});
  const [confirmed,setConfirmed]=useState<Record<string,boolean>>({});
  const [busy,setBusy]=useState("");
  const [problem,setProblem]=useState("");
  const [notice,setNotice]=useState("");
  const refresh=useCallback(async()=>{
    try{
      const data=await load("/api/owner/media/review");
      if(!data||typeof data!=="object"||!("pending" in data)||
         !Array.isArray(data.pending))throw new Error("Unexpected review response");
      setItems(data.pending as Pending[]);setProblem("");
    }catch(error){setProblem(error instanceof Error?error.message:"Review queue unavailable");}
  },[]);
  useEffect(()=>{void refresh();},[refresh]);
  async function decide(item:Pending,action:"approve"|"reject"){
    const reason=reasons[item.id]?.trim()??"";
    if(reason.length<10||reason.length>500||
       (action==="approve"&&!confirmed[item.id])||busy)return;
    setBusy(item.id);setProblem("");setNotice("");
    try{
      const result=await load("/api/owner/media/review",{
        assetId:item.id,action,reason,
        reviewedSha256:action==="approve"?item.sanitizedSha256:undefined,
      });
      if(!result||typeof result!=="object"||!("state" in result))
        throw new Error("Review decision not confirmed");
      setNotice(action==="approve"
        ?"Private asset marked approved after recorded review; public delivery is still disabled."
        :"Asset rejected with retained audit record.");
      setConfirmed(old=>({...old,[item.id]:false}));
      await refresh();
    }catch(error){setProblem(error instanceof Error?error.message:"Decision rejected");}
    finally{setBusy("");}
  }
  return <section className="page" aria-labelledby="media-review-title">
    <p className="eyebrow">Private owner workspace · independent review</p>
    <h1 id="media-review-title">Media review queue</h1>
    <p className="lead">Review sanitized private images, evidence and usage rights. Approving here does not publish an asset or make it accessible to visitors.</p>
    <p><Link href="/owner/media">Back to media registry</Link></p>
    {problem&&<p role="alert">{problem}</p>}
    {notice&&<p role="status">{notice}</p>}
    <button type="button" className="button secondary" onClick={()=>void refresh()}
      disabled={Boolean(busy)}>Refresh review queue</button>
    {items.length===0?<p>No pending records are available for this account.</p>:
      <div style={{display:"grid",gap:"1.5rem",maxWidth:"850px",marginTop:"1rem"}}>
        {items.map(item=>{
          const scanned=Boolean(item.scannedAt&&item.sanitizedSha256);
          const canAct=!busy&&(reasons[item.id]?.trim().length??0)>=10;
          return <section key={item.id} aria-labelledby={"media-"+item.id}
            style={{border:"1px solid #ccd7df",borderRadius:12,padding:"1.25rem"}}>
            <h2 id={"media-"+item.id}>{item.originalFilename}</h2>
            <p>{item.blobStatus==="uploaded"?"Uploaded privately":"No uploaded source"} ·
              {scanned?" Inspected candidate ready":" Inspection incomplete"} · {item.state}</p>
            {scanned?<img
              src={"/api/owner/media/review/"+encodeURIComponent(item.id)+"/preview"}
              alt={item.altDefault||"Sanitized image awaiting review"}
              style={{display:"block",maxWidth:"100%",maxHeight:360,objectFit:"contain"}}
            />:<p role="status">A private preview is unavailable until scanning and sanitization succeed.</p>}
            <p><strong>Alternative text:</strong> {item.altDefault||"Missing"}</p>
            <p><strong>Declared rights:</strong> {item.rightsStatement||"Missing"}</p>
            <p><strong>Scanner:</strong> {item.scanEngine||"Not scanned"}</p>
            <label htmlFor={"reason-"+item.id}>Required review justification (10–500 characters)</label>
            <textarea id={"reason-"+item.id} rows={3} maxLength={500}
              value={reasons[item.id]??""} onChange={e=>setReasons(old=>({
                ...old,[item.id]:e.target.value,
              }))} style={{width:"100%",display:"block"}} />
            <label style={{display:"block",margin:"1rem 0"}}>
              <input type="checkbox" checked={Boolean(confirmed[item.id])}
                onChange={e=>setConfirmed(old=>({...old,[item.id]:e.target.checked}))}/>
              I independently inspected the processed image and reviewed its rights and accessibility description.
            </label>
            <div style={{display:"flex",gap:10,flexWrap:"wrap"}}>
              <button className="button" type="button"
                disabled={!canAct||!scanned||!confirmed[item.id]}
                onClick={()=>void decide(item,"approve")}>Approve privately</button>
              <button className="button secondary" type="button" disabled={!canAct}
                onClick={()=>void decide(item,"reject")}>Reject and retain source</button>
            </div>
          </section>;
        })}
      </div>}
  </section>;
}
