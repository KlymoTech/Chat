"use client";
import {useCallback,useEffect,useState} from "react";
import Link from "next/link";

type Approved={
  id:string;originalFilename:string;altDefault:string;rightsStatement:string;
  publishedAt:string|null;withdrawnAt:string|null;livePageCount:number;
};
async function request(url:string,body?:unknown):Promise<unknown>{
  const response=await fetch(url,{method:body?"POST":"GET",cache:"no-store",
    credentials:"same-origin",
    ...(body?{headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}:{})});
  const value:unknown=await response.json();
  if(!response.ok){
    const message=value&&typeof value==="object"&&"error" in value&&typeof value.error==="string"
      ?value.error:"Cannot access media publication";
    throw new Error(message);
  }
  return value;
}
export default function MediaPublicationConsole(){
  const [assets,setAssets]=useState<Approved[]>([]);
  const [reasons,setReasons]=useState<Record<string,string>>({});
  const [acknowledged,setAcknowledged]=useState<Record<string,boolean>>({});
  const [busy,setBusy]=useState("");
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [loaded,setLoaded]=useState(false);
  const refresh=useCallback(async()=>{
    try{
      const value=await request("/api/owner/media/publication");
      if(!value||typeof value!=="object"||!("media" in value)||
         !Array.isArray(value.media))throw new Error("Invalid media publication response");
      setAssets(value.media as Approved[]);setError("");setLoaded(true);
    }catch(reason){
      setError(reason instanceof Error?reason.message:"Publication listing unavailable");
      setLoaded(false);
    }
  },[]);
  useEffect(()=>{void refresh();},[refresh]);
  async function decide(asset:Approved,action:"publish"|"withdraw"){
    const reason=reasons[asset.id]?.trim()??"";
    if(reason.length<10||reason.length>500||busy ||
      (action==="withdraw" && asset.livePageCount>0 && !acknowledged[asset.id]))return;
    setBusy(asset.id);setError("");setNotice("");
    try{
      await request("/api/owner/media/publication",{assetId:asset.id,action,reason,
        impactAcknowledged:action==="withdraw"?!!acknowledged[asset.id]:false});
      setAcknowledged(old=>({...old,[asset.id]:false}));
      setNotice(action==="publish"?
        "Publication recorded. Public delivery remains subject to separate production configuration.":
        "Withdrawal recorded. New uncached requests will no longer receive the asset.");
      await refresh();
    }catch(cause){setError(cause instanceof Error?cause.message:"Cannot change publication");}
    finally{setBusy("");}
  }
  return <section className="page" aria-labelledby="publication-title">
    <p className="eyebrow">Private owner workspace · media publication</p>
    <h1 id="publication-title">Approved media publication</h1>
    <p className="lead">Human approval and public publication are separate audited actions.
      Withdrawing an image does not delete the original, inspection evidence or prior records.</p>
    <p><Link href="/owner/media/review">Media review</Link> · <Link href="/owner/media">Media registry</Link></p>
    {error&&<p role="alert">{error}</p>}
    {notice&&<p role="status">{notice}</p>}
    <button className="button secondary" disabled={Boolean(busy)} onClick={()=>void refresh()}>Refresh</button>
    {loaded&&assets.length===0?<p>No approved media are available for publication.</p>:null}
    <div style={{display:"grid",gap:"1rem",maxWidth:800,marginTop:"1rem"}}>
      {assets.map(asset=>{
        const live=!!asset.publishedAt&&!asset.withdrawnAt;
        const reason=reasons[asset.id]??"";
        return <section key={asset.id} aria-labelledby={"media-"+asset.id}
          style={{border:"1px solid #cad6db",borderRadius:12,padding:20}}>
          <h2 id={"media-"+asset.id}>{asset.originalFilename}</h2>
          <p>Status: <strong>{live?"Published":asset.withdrawnAt?"Withdrawn":"Approved — private"}</strong></p>
          <p><strong>Alternative text:</strong> {asset.altDefault}</p>
          <p><strong>Declared rights:</strong> {asset.rightsStatement}</p>
          <p><strong>Currently referencing published pages:</strong> {asset.livePageCount}</p>
          {live&&asset.livePageCount>0&&<p role="alert">Withdrawing this image will leave an unavailable image on {asset.livePageCount} published page(s). Review and republish those pages with a replacement where appropriate.</p>}
          {live&&<p><a href={"/media/"+encodeURIComponent(asset.id)} target="_blank"
            rel="noopener noreferrer">Inspect public asset endpoint</a>
            {" "}(only available when delivery is enabled)</p>}
          <label htmlFor={"reason-"+asset.id}>Justification (10–500 characters)</label>
          <textarea id={"reason-"+asset.id} maxLength={500} rows={3}
            style={{display:"block",width:"100%"}}
            value={reason} onChange={event=>setReasons(old=>({...old,[asset.id]:event.target.value}))}/>
          {live&&asset.livePageCount>0&&<label style={{display:"block",margin:"1rem 0"}}>
            <input type="checkbox" checked={!!acknowledged[asset.id]}
              onChange={event=>setAcknowledged(old=>({...old,[asset.id]:event.target.checked}))}/>
            I acknowledge the affected pages and understand this withdrawal takes effect immediately on uncached public requests.
          </label>}
          <button className="button" disabled={!!busy||reason.trim().length<10||
            (live&&asset.livePageCount>0&&!acknowledged[asset.id])}
            onClick={()=>void decide(asset,live?"withdraw":"publish")}>
            {busy===asset.id?"Saving…":live?"Withdraw public asset":"Publish approved asset"}
          </button>
        </section>;
      })}
    </div>
  </section>;
}
