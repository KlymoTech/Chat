"use client";

import {useCallback,useEffect,useState,type ChangeEvent,type FormEvent} from "react";
import Link from "next/link";

type MediaItem={
  id:string;originalFilename:string;claimedMime:string;claimedByteSize:string;
  altDefault:string;rightsStatement:string;state:string;blobStatus:string;createdAt:string;
};
type Source="original"|"licensed"|"ai-generated";
const accepted=new Set(["image/jpeg","image/png","image/webp","image/avif"]);
const maxBytes=10*1024*1024;

async function loadJson(url:string,method:"GET"|"POST"="GET",body?:unknown):Promise<unknown>{
  const response=await fetch(url,{method,cache:"no-store",credentials:"same-origin",
    ...(method==="POST"?{headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}:{})});
  const value:unknown=await response.json();
  if(!response.ok){
    const error=value&&typeof value==="object"&&"error" in value&&
      typeof value.error==="string"?value.error:"Media request failed";
    throw new Error(error);
  }
  return value;
}

export default function MediaIntake(){
  const [items,setItems]=useState<MediaItem[]>([]);
  const [file,setFile]=useState<File|null>(null);
  const [sha,setSha]=useState("");
  const [alt,setAlt]=useState("");
  const [rights,setRights]=useState("");
  const [source,setSource]=useState<Source>("original");
  const [credit,setCredit]=useState("");
  const [generationTool,setGenerationTool]=useState("");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [enabled,setEnabled]=useState(false);
  const [uploadEnabled,setUploadEnabled]=useState(false);
  const [reservedAsset,setReservedAsset]=useState("");

  const refresh=useCallback(async()=>{
    try{
      const value=await loadJson("/api/owner/media");
      if(!value||typeof value!=="object"||!("media" in value)||
         !Array.isArray(value.media))throw new Error("Unexpected media response");
      setItems(value.media as MediaItem[]);
      setUploadEnabled("uploadEnabled" in value && value.uploadEnabled===true);
      setEnabled(true);setError("");
    }catch(e){
      setEnabled(false);
      setError(e instanceof Error?e.message:"Media metadata unavailable");
    }
  },[]);
  useEffect(()=>{void refresh();},[refresh]);

  async function chooseFile(event:ChangeEvent<HTMLInputElement>){
    const candidate=event.target.files?.[0]??null;
    setFile(null);setSha("");setReservedAsset("");setError("");setNotice("");
    if(!candidate)return;
    if(!accepted.has(candidate.type)||candidate.size<1||candidate.size>maxBytes){
      setError("Choose a JPEG, PNG, WebP or AVIF image of 10 MB or less.");
      return;
    }
    setBusy(true);
    try{
      // Local hashing only. No file bytes leave this browser step.
      const hash=await crypto.subtle.digest("SHA-256",await candidate.arrayBuffer());
      setSha(Array.from(new Uint8Array(hash),b=>b.toString(16).padStart(2,"0")).join(""));
      setFile(candidate);
    }catch{setError("Could not calculate file checksum on this device.");}
    finally{setBusy(false);}
  }
  async function uploadFile(assetId:string,candidate:File):Promise<void>{
    if(!uploadEnabled)throw new Error("Private upload is not enabled");
    const result=await fetch("/api/owner/media/"+encodeURIComponent(assetId)+"/upload",{
      method:"PUT",credentials:"same-origin",cache:"no-store",
      headers:{"Content-Type":"application/octet-stream"},
      body:candidate,
    });
    if(!result.ok)throw new Error("Quarantine bytes were not accepted ("+result.status+"). Check storage configuration and file integrity.");
  }
  async function retryUpload(){
    if(!file||!reservedAsset||busy)return;
    setBusy(true);setError("");setNotice("");
    try{
      await uploadFile(reservedAsset,file);
      setNotice("File stored privately in quarantine. Scanning and approval are still pending.");
      setFile(null);setSha("");setReservedAsset("");
      await refresh();
    }catch(error){setError(error instanceof Error?error.message:"Retry failed");}
    finally{setBusy(false);}
  }
  async function reserve(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    if(!file||!sha||busy)return;
    setBusy(true);setError("");setNotice("");
    try{
      const response=await loadJson("/api/owner/media","POST",{
        originalFilename:file.name,claimedMime:file.type,
        claimedSha256:sha,claimedByteSize:file.size,
        altDefault:alt,rightsStatement:rights,
        provenance:{source,credit,generationTool},
      });
      if(!response||typeof response!=="object"||!("assetId" in response)||
         typeof response.assetId!=="string")throw new Error("Unexpected manifest receipt");
      const assetId=response.assetId;
      setReservedAsset(assetId);
      setNotice("Quarantine metadata reserved. File bytes have NOT been transferred.");
      await refresh();
      if(uploadEnabled){
        try{
          await uploadFile(assetId,file);
          setNotice("File stored privately in quarantine. Scanning and approval are still pending.");
          setFile(null);setSha("");setReservedAsset("");
          await refresh();
        }catch(uploadError){
          setError(uploadError instanceof Error?uploadError.message:"Quarantine upload failed");
          setNotice("Metadata is saved, but the image has NOT been confirmed uploaded. Retry below.");
        }
      }
    }catch(e){setError(e instanceof Error?e.message:"Manifest reservation failed");}
    finally{setBusy(false);}
  }

  return <section className="page" aria-labelledby="media-intake-heading">
    <p className="eyebrow">Owner workspace · restricted media metadata</p>
    <h1 id="media-intake-heading">Media quarantine registry</h1>
    <p className="lead">Register image rights and provenance, then optionally store bytes in a private quarantine. Scanning, review and public delivery remain disabled.</p>
    <p><Link href="/owner">Back to owner CMS</Link> · <Link href="/owner/media/review">Independent media review</Link> · <Link href="/owner/media/publish">Media publication</Link></p>
    {error&&<p role="alert">{error}</p>}
    {notice&&<p role="status">{notice}</p>}
    {enabled&&<div style={{display:"grid",gap:"1.5rem",maxWidth:"820px"}}>
      <form onSubmit={e=>void reserve(e)} style={{display:"grid",gap:".75rem"}}>
        <h2>New quarantine manifest</h2>
        <label htmlFor="media-file">Choose an image (JPEG, PNG, WebP or AVIF, maximum 10 MB)</label>
        <input id="media-file" type="file" accept="image/jpeg,image/png,image/webp,image/avif"
          onChange={e=>void chooseFile(e)}/>
        {file&&<p>Selected: {file.name} · {file.size.toLocaleString()} bytes ·
          {sha?" Checksum calculated locally.":" Calculating checksum…"}</p>}
        <label htmlFor="media-alt">Accessible alternative text (required before approval)</label>
        <input id="media-alt" value={alt} maxLength={300} required
          onChange={e=>setAlt(e.target.value)} placeholder="Describe the image's meaning"/>
        <label htmlFor="media-rights">Usage rights and licence statement</label>
        <textarea id="media-rights" value={rights} maxLength={500} required rows={3}
          onChange={e=>setRights(e.target.value)} placeholder="Who owns the image and how may it be used?"/>
        <label htmlFor="media-source">Source/provenance</label>
        <select id="media-source" value={source} onChange={e=>setSource(e.target.value as Source)}>
          <option value="original">Original artwork</option>
          <option value="licensed">Licensed from another party</option>
          <option value="ai-generated">AI-generated image</option>
        </select>
        <label htmlFor="media-credit">Creator, licensor or attribution</label>
        <input id="media-credit" value={credit} maxLength={300}
          required={source==="licensed"} onChange={e=>setCredit(e.target.value)}/>
        {source==="ai-generated"&&<>
          <label htmlFor="media-tool">Generation tool/model (required)</label>
          <input id="media-tool" value={generationTool} maxLength={200} required
            onChange={e=>setGenerationTool(e.target.value)}/>
        </>}
        <button className="button" type="submit" disabled={!file||!sha||busy}>
          {busy?"Please wait…":"Reserve quarantined manifest"}
        </button>
        <p className="owner-hint">{uploadEnabled?
          "After metadata reservation the image bytes are sent to private quarantine, with server-side signature and checksum verification. This does not scan or approve the file.":
          "Private byte upload is disabled; this form reserves metadata only. No file bytes are sent."}
          A separate scanner, metadata-stripping and derivative pipeline are required before public use.</p>
        {reservedAsset&&file&&uploadEnabled&&<button type="button" className="button secondary"
          disabled={busy} onClick={()=>void retryUpload()}>Retry private quarantine upload</button>}
      </form>
      <section aria-labelledby="media-existing">
        <h2 id="media-existing">Site media records</h2>
        <button className="button secondary" type="button" onClick={()=>void refresh()}>Refresh records</button>
        {items.length===0?<p>No registered media metadata yet.</p>:
          <ul>{items.map(item=><li key={item.id}>
            <strong>{item.originalFilename}</strong> — {item.state}, {item.blobStatus}
            <p>{item.altDefault||"No alternative text supplied"} · {item.claimedMime}</p>
          </li>)}</ul>}
      </section>
    </div>}
  </section>;
}
