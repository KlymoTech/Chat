"use client";
import {useEffect,useState} from "react";
import Link from "next/link";
import {parseRedirectDraft,type RedirectDraft} from "../../../lib/redirect-contract";
type RegistryRow={id:string;sourcePath:string;targetPath:string;
  status:"draft"|"approved"|"suspended";reasonCode:string;requestedBy:string;reviewedBy:string|null};
const empty:RedirectDraft={sourcePath:"/content/old-page",targetPath:"/resources",reasonCode:"slug_change"};
async function ownerCall(url:string,method:"GET"|"POST"="GET",body?:unknown):Promise<unknown>{
  const response=await fetch(url,{
    method,credentials:"same-origin",cache:"no-store",
    ...(method==="POST"?{headers:{"Content-Type":"application/json"},
      body:JSON.stringify(body)}:{})});
  const result:unknown=await response.json();
  if(!response.ok)throw Error(result&&typeof result==="object"&&
    "error" in result&&typeof result.error==="string"?result.error:"Redirect operation unavailable");
  return result;
}
export default function RedirectConsole(){
  const [draft,setDraft]=useState<RedirectDraft>(empty);
  const [rows,setRows]=useState<RegistryRow[]>([]);
  const [loading,setLoading]=useState(false);
  const [message,setMessage]=useState("");
  const [error,setError]=useState("");
  const safe=parseRedirectDraft(draft);
  async function refresh(){
    try{
      const result=await ownerCall("/api/owner/redirects") as {redirects?:RegistryRow[]};
      if(!Array.isArray(result.redirects))throw Error("Invalid registry response");
      setRows(result.redirects);
    }catch(e){setError(e instanceof Error?e.message:"Redirect management unavailable");}
  }
  useEffect(()=>{void refresh();},[]);
  async function create(){
    if(!safe||loading)return;
    setLoading(true);setError("");
    try{
      await ownerCall("/api/owner/redirects","POST",safe);
      setMessage("Redirect draft saved. A different owner must approve the route.");
      await refresh();
    }catch(e){setError(e instanceof Error?e.message:"Unable to draft redirect");}
    finally{setLoading(false);}
  }
  async function changeStatus(row:RegistryRow,action:"approve"|"suspend"){
    if(loading)return;
    if(!window.confirm(action==="approve"?
      "Approve only after verifying the old URL is retired and the new destination is correct?":
      "Suspend this live redirect? Visitors will no longer be redirected."))return;
    setLoading(true);setError("");
    try{
      await ownerCall("/api/owner/redirects/"+encodeURIComponent(row.id)+"/"+action,
        "POST",{});
      setMessage(action==="approve"?
        "Redirect approved. Public delivery still requires separately verified reader grants and activation.":
        "Redirect suspended; the old URL will no longer return this mapping.");
      await refresh();
    }catch(e){setError(e instanceof Error?e.message:"Redirect decision denied");}
    finally{setLoading(false);}
  }
  return <section className="page" style={{maxWidth:1050}} aria-labelledby="redirect-title">
    <p className="eyebrow">Owner CMS · SEO governance</p>
    <h1 id="redirect-title">Content redirects</h1>
    <p>Map a retired content URL to a real replacement without open redirects.
      Drafts require independent approval. No destination can contain an external
      host, script URL, query string, fragment or private route.</p>
    <p><Link href="/owner">Back to owner CMS</Link></p>
    {error&&<p role="alert">{error}</p>}
    {message&&<p role="status">{message}</p>}
    <div style={{display:"grid",gap:12}}>
      <label>Retired content URL (e.g. /content/old-page)
        <input value={draft.sourcePath} maxLength={512} onChange={e=>
          setDraft(old=>({...old,sourcePath:e.target.value}))}/></label>
      <label>Internal destination (e.g. /content/new-page or /resources)
        <input value={draft.targetPath} maxLength={512} onChange={e=>
          setDraft(old=>({...old,targetPath:e.target.value}))}/></label>
      <label>Reason for replacement
        <select value={draft.reasonCode} onChange={e=>
          setDraft(old=>({...old,reasonCode:e.target.value as RedirectDraft["reasonCode"]}))}>
          <option value="slug_change">Slug changed</option>
          <option value="consolidated_content">Consolidated content</option>
          <option value="replaced_content">Content replaced</option>
        </select></label>
      <button type="button" className="button" disabled={loading||!safe}
        onClick={()=>void create()}>Create reviewed redirect draft</button>
      {!safe&&<p role="status">Use a valid retired /content/slug URL and a distinct approved internal destination.</p>}
      <h2>Redirect registry</h2>
      {rows.length?<div style={{overflowX:"auto"}}><table style={{width:"100%"}}>
        <thead><tr><th scope="col">Old URL</th><th scope="col">Destination</th>
          <th scope="col">Status</th><th scope="col">Decision</th></tr></thead>
        <tbody>{rows.map(row=><tr key={row.id}>
          <td>{row.sourcePath}</td><td>{row.targetPath}</td>
          <td>{row.status}</td>
          <td>{row.status==="approved"?
            <button type="button" disabled={loading} onClick={()=>void changeStatus(row,"suspend")}>
              Suspend</button>:
            <button type="button" disabled={loading} onClick={()=>void changeStatus(row,"approve")}>
              Request approval</button>}</td>
        </tr>)}</tbody>
      </table></div>:<p>No redirect records loaded. Owner permissions and database activation may be required.</p>}
    </div>
  </section>;
}
