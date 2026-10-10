"use client";

import { useCallback, useEffect, useState, useReducer, type FormEvent, type SetStateAction } from "react";
import Link from "next/link";
import { PublishedBlocks } from "../../components/PublishedBlocks";
import type { PublicBlock } from "../../lib/cms";
import { freshBuilderBlock } from "../../lib/builder-contract";
import {BUILDER_TEMPLATES,instantiateTemplate,type BuilderTemplateId} from "../../lib/builder-templates";
import {createRecovery,parseRecovery,recoveryStorageKey,type DraftRecovery} from "../../lib/editor-recovery";
import "./owner.css";

type Page={id:string;path:string;locale:string;publishedRevisionId:string|null;publishedTitle:string|null;trashedAt:string|null};
type Revision={id:string;revision:number;state:string;title:string;description:string;blocks:PublicBlock[];createdAt:string;authorId:string};
type Document={title:string;description:string;blocks:PublicBlock[]};
const emptyDoc:Document={title:"",description:"",blocks:[]};
type HistoryState={present:Document;past:Document[];future:Document[]};
type HistoryAction=
  | {kind:"edit";value:SetStateAction<Document>}
  | {kind:"reset";value:Document}
  | {kind:"undo"|"redo"};
function builderHistory(state:HistoryState,action:HistoryAction):HistoryState {
  if(action.kind==="reset")return {present:action.value,past:[],future:[]};
  if(action.kind==="undo") {
    if(!state.past.length)return state;
    return {present:state.past[state.past.length-1],past:state.past.slice(0,-1),
      future:[state.present,...state.future].slice(0,40)};
  }
  if(action.kind==="redo"){
    if(!state.future.length)return state;
    return {present:state.future[0],past:[...state.past,state.present].slice(-40),
      future:state.future.slice(1)};
  }
  const next=typeof action.value==="function"?action.value(state.present):action.value;
  if(next===state.present)return state;
  return {present:next,past:[...state.past,state.present].slice(-40),future:[]};
}

async function requestJson(url:string,method:"GET"|"POST"="GET",body?:unknown):Promise<unknown>{
  const response=await fetch(url,{method,credentials:"same-origin",cache:"no-store",
    ...(method==="POST"?{headers:{"Content-Type":"application/json"},body:JSON.stringify(body??{})}:{})});
  const data:unknown=await response.json();
  if(!response.ok) {
    const message=data&&typeof data==="object"&&"error" in data&&typeof data.error==="string"
      ?data.error:"Action was not confirmed";
    throw Object.assign(new Error(message),{status:response.status});
  }
  return data;
}
function hasArray(value:unknown,key:"pages"|"revisions"):value is Record<typeof key,unknown[]> {
  return !!value&&typeof value==="object"&&key in value&&Array.isArray((value as Record<string,unknown>)[key]);
}
export default function OwnerConsole(){
  const [connection,setConnection]=useState<"loading"|"ready"|"signed-out"|"disabled"|"error">("loading");
  const [pages,setPages]=useState<Page[]>([]);
  const [selected,setSelected]=useState("");
  const [ownerScope,setOwnerScope]=useState<{actorId:string;siteId:string}|null>(null);
  const [recoveryOptIn,setRecoveryOptIn]=useState(false);
  const [recoverable,setRecoverable]=useState<DraftRecovery|null>(null);
  const [recoveryVersion,setRecoveryVersion]=useState<number|null>(null);
  const [revisions,setRevisions]=useState<Revision[]>([]);
  const [revisionId,setRevisionId]=useState("");
  const [history,dispatch]=useReducer(builderHistory,{
    present:emptyDoc,past:[],future:[],
  });
  const doc=history.present;
  const [acknowledgedDoc,setAcknowledgedDoc]=useState(JSON.stringify(emptyDoc));
  const hasUnsavedChanges=JSON.stringify(doc)!==acknowledgedDoc;
  const setDoc=(value:SetStateAction<Document>)=>dispatch({kind:"edit",value});
  const resetDoc=(value:Document)=>dispatch({kind:"reset",value});
  const [slug,setSlug]=useState("");
  const [locale,setLocale]=useState("en");
  const [reason,setReason]=useState("");
  const [blogCategory,setBlogCategory]=useState("general");
  const [blogTags,setBlogTags]=useState("");
  const [blogClassified,setBlogClassified]=useState(false);
  const [previewMode,setPreviewMode]=useState<"desktop"|"tablet"|"mobile">("desktop");
  const [busy,setBusy]=useState(false);
  const [notice,setNotice]=useState("");
  const [problem,setProblem]=useState("");

  const refresh=useCallback(async()=>{
    try {
      const result=await requestJson("/api/owner/pages");
      if(!hasArray(result,"pages"))throw new Error("Unexpected CMS response");
      setPages(result.pages as Page[]);
      const ownerInfo=result as Record<string,unknown>;
      if(typeof ownerInfo.actorId==="string"&&typeof ownerInfo.siteId==="string")
        setOwnerScope({actorId:ownerInfo.actorId,siteId:ownerInfo.siteId});
      else setOwnerScope(null);
      setConnection("ready");setProblem("");
    }catch(error){
      const status=(error as {status?:number}).status;
      setConnection(status===401?"signed-out":status===503?"disabled":"error");
      setProblem(error instanceof Error?error.message:"Unable to load owner pages");
    }
  },[]);
  useEffect(()=>{void refresh();},[refresh]);
  useEffect(()=>{
    if(!hasUnsavedChanges)return;
    const protect=(event:BeforeUnloadEvent)=>{
      event.preventDefault();
      event.returnValue="";
    };
    window.addEventListener("beforeunload",protect);
    return ()=>window.removeEventListener("beforeunload",protect);
  },[hasUnsavedChanges]);

  useEffect(()=>{
    if(!recoveryOptIn||!ownerScope||!selected||!hasUnsavedChanges ||
       connection!=="ready"||process.env.NEXT_PUBLIC_EDITOR_RECOVERY_ENABLED!=="true")return;
    const token=window.setTimeout(()=>{
      const raw=createRecovery({
        siteId:ownerScope.siteId,ownerId:ownerScope.actorId,pageId:selected,
        expectedVersion:recoveryVersion??revisions.reduce((m,r)=>Math.max(m,r.revision),0),
        document:doc,
      });
      if(!raw)return;
      try{window.sessionStorage.setItem(recoveryStorageKey(
        ownerScope.siteId,ownerScope.actorId,selected),raw);}
      catch{/* Device storage unavailable; editor remains unsaved. */}
    },800);
    return ()=>window.clearTimeout(token);
  },[doc,hasUnsavedChanges,ownerScope,selected,recoveryOptIn,recoveryVersion,
     revisions,connection]);
  function recoveryKey(pageId:string):string|null{
    if(!ownerScope)return null;
    try{return recoveryStorageKey(ownerScope.siteId,ownerScope.actorId,pageId);}
    catch{return null;}
  }
  function clearRecovery(pageId:string){
    const key=recoveryKey(pageId);
    if(key)try{window.sessionStorage.removeItem(key);}catch{}
    setRecoverable(null);setRecoveryVersion(null);
  }
  function restoreRecovery(){
    if(!recoverable||!ownerScope||recoverable.pageId!==selected)return;
    if(hasUnsavedChanges&&!window.confirm(
      "Restore this earlier session snapshot and replace the current unsaved editor state?"))return;
    resetDoc(recoverable.document);
    setRecoveryVersion(recoverable.expectedVersion);
    setAcknowledgedDoc(JSON.stringify(emptyDoc));
    setRecoveryOptIn(true);
    setRecoverable(null);
    setNotice("Unpublished session snapshot restored. Review the latest server revision before saving.");
  }
  const loadRevisions=useCallback(async(id:string)=>{
    if(!id){setRevisions([]);setRevisionId("");return;}
    const result=await requestJson("/api/owner/pages/"+encodeURIComponent(id)+"/revisions");
    if(!hasArray(result,"revisions"))throw new Error("Unexpected revision history");
    setRevisions(result.revisions as Revision[]);setRevisionId("");
  },[]);
  async function choose(id:string){
    if(id!==selected && hasUnsavedChanges &&
       !window.confirm("You have unsaved local edits. Continue without saving them?"))return;
    if(id!==selected && hasUnsavedChanges && selected && recoveryOptIn &&
       ownerScope && process.env.NEXT_PUBLIC_EDITOR_RECOVERY_ENABLED==="true"){
      const copy=createRecovery({
        siteId:ownerScope.siteId,ownerId:ownerScope.actorId,pageId:selected,
        expectedVersion:recoveryVersion??revisions.reduce((m,r)=>Math.max(m,r.revision),0),
        document:doc,
      });
      const key=recoveryKey(selected);
      if(copy&&key)try{window.sessionStorage.setItem(key,copy);}catch{}
    }
    // No silent reuse of another page's private editor state.
    setSelected(id);setNotice("");setProblem("");
    resetDoc(emptyDoc);setAcknowledgedDoc(JSON.stringify(emptyDoc));
    setRecoverable(null);setRecoveryOptIn(false);setRecoveryVersion(null);
    const key=recoveryKey(id);
    if(key&&process.env.NEXT_PUBLIC_EDITOR_RECOVERY_ENABLED==="true"){
      try{
        const draft=parseRecovery(window.sessionStorage.getItem(key),{
          siteId:ownerScope!.siteId,ownerId:ownerScope!.actorId,pageId:id,
        });
        if(draft)setRecoverable(draft);
        else window.sessionStorage.removeItem(key);
      }catch{}
    }
    setBlogCategory("general");setBlogTags("");setBlogClassified(false);
    try{await loadRevisions(id);}catch(error){setProblem(error instanceof Error?error.message:"Revision history unavailable");}
    try{
      const result=await requestJson("/api/owner/pages/"+encodeURIComponent(id)+"/blog");
      if(result&&typeof result==="object"&&"blog" in result){
        const info=(result as {blog?:{category?:string;tags?:string[]}|null}).blog;
        if(info&&typeof info.category==="string"&&Array.isArray(info.tags)){
          setBlogCategory(info.category);setBlogTags(info.tags.join(", "));
          setBlogClassified(true);
        }
      }
    }catch{setProblem("Blog classification could not be loaded.");}
  }
  function addTemplate(template:BuilderTemplateId){
    const blocks=instantiateTemplate(template,()=>crypto.randomUUID());
    setDoc(old=>old.blocks.length+blocks.length>100?old:
      {...old,blocks:[...old.blocks,...blocks]});
    setNotice("Layout inserted locally. Replace placeholders and save a new reviewed draft.");
  }
  function addBlock(type:PublicBlock["type"]){
    const blockId=crypto.randomUUID();
    const block:PublicBlock=type==="hero"||type==="cta"||type==="faq"?
      freshBuilderBlock(type,blockId):
      type==="image"?{type,blockId,schemaVersion:1,assetId:"",alt:"",caption:""}:
      type==="callout"?{type,blockId,schemaVersion:1,title:"New callout",body:""}:
      {type,blockId,schemaVersion:1,text:"New text"};
    setDoc(old=>({...old,blocks:[...old.blocks,block]}));
  }
  function editVisual(index:number,changes:Partial<PublicBlock>){
    setDoc(old=>({...old,blocks:old.blocks.map((block,i)=>
      i===index?{...block,...changes} as PublicBlock:block)}));
  }
  function duplicateBlock(index:number) {
    setDoc(old=>{
      const source=old.blocks[index];
      if(!source||old.blocks.length>=100)return old;
      const duplicate={...structuredClone(source),blockId:crypto.randomUUID(),schemaVersion:1} as PublicBlock;
      const blocks=[...old.blocks];
      blocks.splice(index+1,0,duplicate);
      return {...old,blocks};
    });
  }
  function updateImage(index:number,field:"assetId"|"alt"|"caption",value:string){
    setDoc(old=>({...old,blocks:old.blocks.map((block,i)=>
      i===index && block.type==="image"?{...block,[field]:value}:block
    )}));
  }
  function updateBlock(index:number,field:"text"|"title"|"body",value:string){
    setDoc(old=>({...old,blocks:old.blocks.map((block,i)=>{
      if(i!==index)return block;
      if(block.type==="callout")return {...block,[field]:value};
      return field==="text"?{...block,text:value}:block;
    })}));
  }
  function moveBlock(index:number,offset:number){
    setDoc(old=>{
      const blocks=[...old.blocks],target=index+offset;
      if(target<0||target>=blocks.length)return old;
      [blocks[index],blocks[target]]=[blocks[target],blocks[index]];
      return {...old,blocks};
    });
  }
  function loadRevision(){
    const current=revisions.find(r=>r.id===revisionId);
    if(!current)return;
    if(hasUnsavedChanges &&
       !window.confirm("Loading a revision will replace unsaved local edits. Continue?"))return;
    const restored={title:current.title,description:current.description,
      blocks:current.blocks.map(b=>({...b}))};
    resetDoc(restored);
    setAcknowledgedDoc(JSON.stringify(restored));
    clearRecovery(selected);
  }
  async function act(url:string,body:unknown,success:string,onAcknowledged?:()=>void){
    if(busy)return;
    setBusy(true);setNotice("");setProblem("");
    try{
      await requestJson(url,"POST",body);
      onAcknowledged?.();
      setNotice(success);await refresh();
      if(selected)await loadRevisions(selected);
    }catch(error){setProblem(error instanceof Error?error.message:"Operation was not confirmed");}
    finally{setBusy(false);}
  }
  async function create(event:FormEvent){
    event.preventDefault();
    if(!slug.trim())return;
    await act("/api/owner/pages",{path:"/content/"+slug.trim().toLowerCase(),locale,document:doc},
      "Page and first draft created. Choose the page to continue reviewing.");
  }
  async function signOut(){
    setBusy(true);setNotice("");setProblem("");
    try{
      await requestJson("/api/owner/auth/logout","POST",{});
      if(ownerScope)try{
        const prefix=["website","cms-recovery","v1",ownerScope.siteId,
          ownerScope.actorId].join(":")+":";
        for(let i=window.sessionStorage.length-1;i>=0;i--){
          const key=window.sessionStorage.key(i);
          if(key?.startsWith(prefix))window.sessionStorage.removeItem(key);
        }
      }catch{}
      setRecoveryOptIn(false);setRecoverable(null);setRecoveryVersion(null);
      setOwnerScope(null);
      setConnection("signed-out");setPages([]);setRevisions([]);setSelected("");
      setNotice("Local owner session ended.");
    }catch{setProblem("Unable to confirm sign-out");}
    finally{setBusy(false);}
  }
  if(connection!=="ready")return <section className="owner-console" aria-labelledby="owner-title">
    <p className="eyebrow">Private content workspace</p><h1 id="owner-title">Owner CMS</h1>
    {connection==="loading"?<p role="status">Checking access…</p>:<>
      <p role="status">{connection==="disabled"?
        "Owner CMS activation is blocked until identity and database isolation are approved.":
        connection==="signed-out"?"Sign in through your organization’s identity provider.":
        "The workspace is unavailable."}</p>
      {problem&&<p>{problem}</p>}
      <div className="owner-actions">
        <a className="button" href="/api/owner/auth/login">Sign in</a>
        <button className="button secondary" onClick={()=>void refresh()}>Retry</button>
      </div>
    </>}
  </section>;

  const chosen=pages.find(p=>p.id===selected);
  const latestRevisionNumber=revisions.reduce((max,r)=>Math.max(max,r.revision),0);
  return <section className="owner-console" aria-labelledby="owner-title">
    <div className="owner-heading">
      <div><p className="eyebrow">Authenticated content workspace</p><h1 id="owner-title">Owner CMS</h1>
        <p>Edits are drafts. Publication needs independent approval and downstream refresh.</p></div>
      <div className="owner-actions"><Link href="/owner/media">Media quarantine</Link><Link href="/owner/media/review">Media review</Link><Link href="/owner/media/publish">Media publication</Link><Link href="/owner/analytics">Analytics</Link><Link href="/owner/automations">Automations</Link><Link href="/owner/privacy/rights">Privacy rights</Link><Link href="/owner/redirects">Redirects</Link><Link href="/resources">Public resources</Link>
        <button className="button secondary" onClick={()=>void signOut()} disabled={busy}>Sign out</button></div>
    </div>
    {notice&&<p className="owner-message" role="status">{notice}</p>}
    {problem&&<p className="owner-error" role="alert">{problem}</p>}
    <div className="owner-grid">
      <aside className="owner-panel">
        <h2>Pages</h2>
        <button className="button secondary" disabled={busy} onClick={()=>void refresh()}>Refresh</button>
        {pages.length===0?<p>No pages yet.</p>:<ul className="owner-pages">
          {pages.map(page=><li key={page.id}><button
            className={selected===page.id?"owner-selected":""}
            onClick={()=>void choose(page.id)}>
            <span>{page.path}</span><small>{page.trashedAt?"In trash":page.publishedRevisionId?"Published":"Draft only"}</small>
          </button></li>)}</ul>}
      </aside>
      <div className="owner-work">
        <section className="owner-panel">
          <h2>Create a content page</h2>
          <form className="owner-form" onSubmit={event=>void create(event)}>
            <label htmlFor="new-slug">Slug (under /content/)</label>
            <input id="new-slug" required pattern="[a-z0-9]+(?:-[a-z0-9]+)*" value={slug}
              onChange={event=>setSlug(event.target.value)} placeholder="example-article"/>
            <label htmlFor="new-locale">Locale</label>
            <select id="new-locale" value={locale} onChange={event=>setLocale(event.target.value)}>
              <option value="en">English</option>
            </select>
            <p className="owner-hint">Creating uses the draft in the block editor below. Nothing is automatically published.</p>
            <button className="button" type="submit" disabled={busy}>Create page and draft</button>
          </form>
        </section>
        {chosen&&<section className="owner-panel">
          <h2>Selected page</h2><p><strong>{chosen.path}</strong> · {chosen.locale}</p>
          <p>{chosen.trashedAt?"In trash":chosen.publishedRevisionId?"Published":"Unpublished"}</p>
          {chosen.publishedRevisionId&&!chosen.trashedAt&&<Link href={chosen.path}>Open public page</Link>}
          <h3>Revision history</h3>
          <label htmlFor="revision-select">Revision</label>
          <select id="revision-select" value={revisionId} onChange={e=>setRevisionId(e.target.value)}>
            <option value="">Choose a revision</option>
            {revisions.map(r=><option key={r.id} value={r.id}>#{r.revision} · {r.state} · {r.title}</option>)}
          </select>
          <div className="owner-actions">
            <button className="button secondary" disabled={!revisionId||busy} onClick={loadRevision}>Load into editor</button>
            <button className="button secondary" disabled={!revisionId||busy||!!chosen.trashedAt}
              onClick={()=>void act("/api/owner/pages/"+chosen.id+"/approve",{revisionId},"Revision approved.")}>Approve</button>
            <button className="button" disabled={!revisionId||busy||!!chosen.trashedAt}
              onClick={()=>void act("/api/owner/pages/"+chosen.id+"/publish",{revisionId},"Publication committed; public cache refresh pending.")}>Publish</button>
            <button className="button secondary" disabled={!revisionId||busy||!!chosen.trashedAt}
              onClick={()=>void act("/api/owner/pages/"+chosen.id+"/restore",{revisionId},"Previous published revision restored; refresh pending.")}>Rollback</button>
          </div>
          <div className="owner-preserve">
            <h3>Blog classification</h3>
            <p className="owner-hint">{blogClassified?"This page is marked as a blog article.":"Optional: classify this unpublished page as a blog article."}</p>
            <label htmlFor="blog-category-input">Category slug</label>
            <input id="blog-category-input" value={blogCategory} maxLength={60}
              pattern="[a-z0-9]+(-[a-z0-9]+)*"
              onChange={e=>setBlogCategory(e.target.value)} />
            <label htmlFor="blog-tag-input">Tags (comma-separated, up to 8)</label>
            <input id="blog-tag-input" value={blogTags} maxLength={500}
              onChange={e=>setBlogTags(e.target.value)} placeholder="updates, guidance"/>
            <button className="button secondary"
              disabled={busy||!!chosen.trashedAt||!!chosen.publishedRevisionId}
              onClick={()=>void act("/api/owner/pages/"+chosen.id+"/blog",{
                category:blogCategory,
                tags:blogTags.split(",").map(tag=>tag.trim()).filter(Boolean)
              },"Blog classification saved for editorial review.")}>
              {blogClassified?"Update draft blog classification":"Mark as blog article"}
            </button>
            <p className="owner-hint">Classification locks after publication; editorial changes must be reviewed.</p>
          </div>
          <div className="owner-preserve">
            <h3>Manual preservation</h3>
            <label htmlFor="trash-reason">Reason (10–500 characters)</label>
            <textarea id="trash-reason" rows={2} maxLength={500} value={reason}
              onChange={e=>setReason(e.target.value)}/>
            <button className="button secondary" disabled={busy||reason.trim().length<10}
              onClick={()=>void act("/api/owner/pages/"+chosen.id+"/preservation",
                {action:chosen.trashedAt?"restore":"trash",reason},
                chosen.trashedAt?"Restored as unpublished.":"Moved to trash; public reconciliation pending.")}>
              {chosen.trashedAt?"Restore from trash":"Move to trash"}
            </button>
            <p className="owner-hint">No automated expiry or permanent deletion is available.</p>
          </div>
        </section>}
        <section className="owner-panel">
          <h2>Block editor</h2>
          <p className="owner-hint">Changes are local until the server acknowledges a new draft.</p>
          {process.env.NEXT_PUBLIC_EDITOR_RECOVERY_ENABLED==="true"&&selected&&<>
            <label className="owner-hint">
              <input type="checkbox" checked={recoveryOptIn}
                onChange={event=>{
                  const yes=event.target.checked;
                  setRecoveryOptIn(yes);
                  if(!yes)clearRecovery(selected);
                }}/>
              Keep a temporary, unpublished recovery copy in this browser tab (up to 2 hours).
            </label>
            <p className="owner-hint">Use only on a trusted device. Browser session storage is not
              encrypted by this application. Recovery never approves or publishes content;
              successful sign-out clears recovery copies for this owner in this tab.</p>
            {recoverable&&<section className="owner-preserve" aria-label="Interrupted draft recovery">
              <strong>Recoverable unpublished changes found</strong>
              <p>Saved at {new Date(recoverable.storedAt).toLocaleString()}.
                Snapshot server revision: {recoverable.expectedVersion}.</p>
              <button type="button" className="button secondary" onClick={restoreRecovery}>
                Restore local snapshot</button>
              <button type="button" className="button secondary"
                onClick={()=>clearRecovery(selected)}>Discard recovery copy</button>
            </section>}
          </>}

          <p role="status" aria-live="polite" className="owner-hint">
            {hasUnsavedChanges?"Unsaved local edits — not yet committed.":
              "Editor content loaded or acknowledged by the server."}
          </p>
          <div className="owner-form">
            <label htmlFor="page-title">Title</label><input id="page-title" value={doc.title} maxLength={180}
              onChange={e=>setDoc(old=>({...old,title:e.target.value}))}/>
            <label htmlFor="page-desc">Description</label><textarea id="page-desc" value={doc.description}
              maxLength={500} rows={2} onChange={e=>setDoc(old=>({...old,description:e.target.value}))}/>
            <div className="owner-actions">
              <button onClick={()=>addBlock("heading")}>Add heading</button>
              <button onClick={()=>addBlock("paragraph")}>Add paragraph</button>
              <button onClick={()=>addBlock("callout")}>Add callout</button>
              <button onClick={()=>addBlock("image")}>Add approved image</button>
              <label className="owner-template-picker">Reusable page layout
                <select defaultValue="" aria-label="Insert page layout"
                  onChange={e=>{if(e.target.value){
                    addTemplate(e.target.value as BuilderTemplateId);e.target.value="";
                  }}}>
                  <option value="">Choose an approved layout</option>
                  {BUILDER_TEMPLATES.map(t=><option value={t.id} key={t.id}>{t.title}</option>)}
                </select>
              </label>
              <button onClick={()=>addBlock("hero")}>Add hero section</button>
              <button onClick={()=>addBlock("cta")}>Add CTA section</button>
              <button onClick={()=>addBlock("faq")}>Add FAQ section</button>
              <button type="button" disabled={!history.past.length} onClick={()=>dispatch({kind:"undo"})}>Undo</button>
              <button type="button" disabled={!history.future.length} onClick={()=>dispatch({kind:"redo"})}>Redo</button>
            </div>
            {doc.blocks.map((block,i)=><fieldset className="owner-block" key={i}>
              <legend>{block.type} #{i+1} <small>{block.blockId?.slice(0,8)??"legacy"}</small></legend>
              {(block.type==="hero"||block.type==="cta")?<>
                {block.type==="hero"&&<label>Eyebrow
                  <input maxLength={100} value={block.eyebrow}
                    onChange={e=>editVisual(i,{eyebrow:e.target.value} as Partial<PublicBlock>)}/>
                </label>}
                <label>Section heading<input maxLength={180} value={block.heading}
                  onChange={e=>editVisual(i,{heading:e.target.value} as Partial<PublicBlock>)}/></label>
                <label>Section description<textarea maxLength={1200} value={block.description}
                  onChange={e=>editVisual(i,{description:e.target.value} as Partial<PublicBlock>)}/></label>
                <label>Action label<input maxLength={80} value={block.actionLabel}
                  onChange={e=>editVisual(i,{actionLabel:e.target.value} as Partial<PublicBlock>)}/></label>
                <label>Internal action path<input value={block.actionPath}
                  onChange={e=>editVisual(i,{actionPath:e.target.value} as Partial<PublicBlock>)}/>
                </label>
                <label>Design variant<select value={block.variant}
                  onChange={e=>editVisual(i,{variant:e.target.value} as Partial<PublicBlock>)}>
                    {block.type==="hero"?<>
                      <option value="center">Centered</option><option value="split">Split</option>
                    </>:<><option value="solid">Solid</option><option value="outline">Outline</option></>}
                  </select></label>
              </>:block.type==="faq"?<>
                {block.items.map((item,j)=><div key={j}>
                  <label>Question {j+1}<input value={item.question} maxLength={240}
                    onChange={e=>editVisual(i,{items:block.items.map((it,k)=>k===j?{...it,question:e.target.value}:it)} as Partial<PublicBlock>)}/></label>
                  <label>Answer {j+1}<textarea value={item.answer} maxLength={2000}
                    onChange={e=>editVisual(i,{items:block.items.map((it,k)=>k===j?{...it,answer:e.target.value}:it)} as Partial<PublicBlock>)}/></label>
                  <button type="button" disabled={block.items.length<=1} onClick={()=>editVisual(i,
                    {items:block.items.filter((_,k)=>k!==j)} as Partial<PublicBlock>)}>Remove question</button>
                </div>)}
                <button type="button" disabled={block.items.length>=20}
                  onClick={()=>editVisual(i,{items:[...block.items,{question:"New question",answer:"Add approved answer"}]} as Partial<PublicBlock>)}>
                  Add FAQ question</button>
              </>:block.type==="image"?<>
                <label>Published media UUID
                  <input value={block.assetId} maxLength={36} placeholder="Approved, published asset UUID"
                    onChange={e=>updateImage(i,"assetId",e.target.value.trim())}/>
                </label>
                <label>Alternative text
                  <textarea value={block.alt} maxLength={300} rows={2}
                    onChange={e=>updateImage(i,"alt",e.target.value)}/>
                </label>
                <label>Caption (optional)
                  <textarea value={block.caption} maxLength={500} rows={2}
                    onChange={e=>updateImage(i,"caption",e.target.value)}/>
                </label>
                <p className="owner-hint">Only approved and separately published same-site media will be accepted for page publication.
                  <Link href="/owner/media/publish">Open approved media registry</Link>.</p>
              </>:block.type==="callout"?<>
                <label>Callout title<input value={block.title} maxLength={180} onChange={e=>updateBlock(i,"title",e.target.value)}/></label>
                <label>Callout body<textarea value={block.body} maxLength={10000} rows={3} onChange={e=>updateBlock(i,"body",e.target.value)}/></label>
              </>:<label>Text<textarea value={block.text} rows={block.type==="heading"?2:4} maxLength={10000}
                onChange={e=>updateBlock(i,"text",e.target.value)}/></label>}
              <div className="owner-actions">
                <button disabled={i===0} onClick={()=>moveBlock(i,-1)}>Up</button>
                <button disabled={i===doc.blocks.length-1} onClick={()=>moveBlock(i,1)}>Down</button>
                <button type="button" disabled={doc.blocks.length>=100} onClick={()=>duplicateBlock(i)}>Duplicate</button>
                <button onClick={()=>setDoc(old=>({...old,blocks:old.blocks.filter((_,j)=>j!==i)}))}>Remove</button>
              </div>
            </fieldset>)}
            {chosen&&<>
              {recoveryVersion!==null&&recoveryVersion!==latestRevisionNumber&&<>
                <p role="alert" className="owner-error">Recovered draft was based on revision {recoveryVersion},
                  but latest server revision is {latestRevisionNumber}. Compare both before creating a new draft.</p>
                <button type="button" className="button secondary"
                  onClick={()=>{
                    if(window.confirm("I compared the recovered draft with the latest server revision and want to append it as a new draft.")){
                      setRecoveryVersion(null);
                      setNotice("Revision conflict acknowledged; a new draft may be saved after review.");
                    }
                  }}>Confirm comparison and permit a new draft</button>
              </>}
              <p className="owner-hint">Latest server revision: {latestRevisionNumber||"not loaded"}.
                Saving appends a new draft only if this is still the current server version.
                A conflict keeps your local edits for review.</p>
              <button className="button" type="button"
                disabled={busy||!!chosen.trashedAt||latestRevisionNumber<1||
                  (recoveryVersion!==null&&recoveryVersion!==latestRevisionNumber)}
                onClick={()=>void act("/api/owner/pages/"+chosen.id+"/draft",
                  {document:doc,expectedVersion:latestRevisionNumber},
                  "New draft revision acknowledged by the server.",
                  ()=>{setAcknowledgedDoc(JSON.stringify(doc));clearRecovery(chosen.id);})}>
                Save new draft revision</button>
            </>}
          </div>
          <section className="owner-preview" aria-label="Local unpublished preview">
            <h3>Local preview — unpublished</h3>
            <p className="owner-hint">Viewport widths are layout aids, not evidence of an actual
              browser or device accessibility test. Nothing here is published.</p>
            <div role="group" aria-label="Preview viewport width" className="owner-preview-modes">
              {(["desktop","tablet","mobile"] as const).map(mode=>
                <button type="button" key={mode} aria-pressed={previewMode===mode}
                  onClick={()=>setPreviewMode(mode)}>
                  {mode==="desktop"?"Desktop (1200px)":mode==="tablet"?"Tablet (768px)":"Mobile (390px)"}
                </button>)}
            </div>
            <p role="status" className="owner-hint">Preview: {previewMode}</p>
            <div className="owner-preview-scroll">
              <div className={"owner-preview-device owner-preview-device-"+previewMode}
                aria-label={previewMode+" unpublished page preview"}>
                <h2>{doc.title||"Untitled"}</h2>
                <p>{doc.description}</p>
                <PublishedBlocks blocks={doc.blocks}/>
              </div>
            </div>
          </section>
        </section>
      </div>
    </div>
  </section>;
}
