"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { PublishedBlocks } from "../../components/PublishedBlocks";
import type { PublicBlock } from "../../lib/cms";
import "./owner.css";

type Page={id:string;path:string;locale:string;publishedRevisionId:string|null;publishedTitle:string|null;trashedAt:string|null};
type Revision={id:string;revision:number;state:string;title:string;description:string;blocks:PublicBlock[];createdAt:string;authorId:string};
type Document={title:string;description:string;blocks:PublicBlock[]};
const emptyDoc:Document={title:"",description:"",blocks:[]};

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
  const [revisions,setRevisions]=useState<Revision[]>([]);
  const [revisionId,setRevisionId]=useState("");
  const [doc,setDoc]=useState<Document>(emptyDoc);
  const [slug,setSlug]=useState("");
  const [locale,setLocale]=useState("en");
  const [reason,setReason]=useState("");
  const [blogCategory,setBlogCategory]=useState("general");
  const [blogTags,setBlogTags]=useState("");
  const [blogClassified,setBlogClassified]=useState(false);
  const [busy,setBusy]=useState(false);
  const [notice,setNotice]=useState("");
  const [problem,setProblem]=useState("");

  const refresh=useCallback(async()=>{
    try {
      const result=await requestJson("/api/owner/pages");
      if(!hasArray(result,"pages"))throw new Error("Unexpected CMS response");
      setPages(result.pages as Page[]);setConnection("ready");setProblem("");
    }catch(error){
      const status=(error as {status?:number}).status;
      setConnection(status===401?"signed-out":status===503?"disabled":"error");
      setProblem(error instanceof Error?error.message:"Unable to load owner pages");
    }
  },[]);
  useEffect(()=>{void refresh();},[refresh]);

  const loadRevisions=useCallback(async(id:string)=>{
    if(!id){setRevisions([]);setRevisionId("");return;}
    const result=await requestJson("/api/owner/pages/"+encodeURIComponent(id)+"/revisions");
    if(!hasArray(result,"revisions"))throw new Error("Unexpected revision history");
    setRevisions(result.revisions as Revision[]);setRevisionId("");
  },[]);
  async function choose(id:string){
    setSelected(id);setNotice("");setProblem("");
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
  function addBlock(type:PublicBlock["type"]){
    setDoc(old=>({...old,blocks:[...old.blocks,type==="callout"?{type,title:"",body:""}:{type,text:""}]}));
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
    if(current)setDoc({title:current.title,description:current.description,blocks:current.blocks.map(b=>({...b}))});
  }
  async function act(url:string,body:unknown,success:string){
    if(busy)return;
    setBusy(true);setNotice("");setProblem("");
    try{
      await requestJson(url,"POST",body);
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
  return <section className="owner-console" aria-labelledby="owner-title">
    <div className="owner-heading">
      <div><p className="eyebrow">Authenticated content workspace</p><h1 id="owner-title">Owner CMS</h1>
        <p>Edits are drafts. Publication needs independent approval and downstream refresh.</p></div>
      <div className="owner-actions"><Link href="/owner/media">Media quarantine</Link><Link href="/owner/media/review">Media review</Link><Link href="/resources">Public resources</Link>
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
          <p className="owner-hint">Changes are local until you save a new draft.</p>
          <div className="owner-form">
            <label htmlFor="page-title">Title</label><input id="page-title" value={doc.title} maxLength={180}
              onChange={e=>setDoc(old=>({...old,title:e.target.value}))}/>
            <label htmlFor="page-desc">Description</label><textarea id="page-desc" value={doc.description}
              maxLength={500} rows={2} onChange={e=>setDoc(old=>({...old,description:e.target.value}))}/>
            <div className="owner-actions">
              <button onClick={()=>addBlock("heading")}>Add heading</button>
              <button onClick={()=>addBlock("paragraph")}>Add paragraph</button>
              <button onClick={()=>addBlock("callout")}>Add callout</button>
            </div>
            {doc.blocks.map((block,i)=><fieldset className="owner-block" key={i}>
              <legend>{block.type} #{i+1}</legend>
              {block.type==="callout"?<>
                <label>Callout title<input value={block.title} maxLength={180} onChange={e=>updateBlock(i,"title",e.target.value)}/></label>
                <label>Callout body<textarea value={block.body} maxLength={10000} rows={3} onChange={e=>updateBlock(i,"body",e.target.value)}/></label>
              </>:<label>Text<textarea value={block.text} rows={block.type==="heading"?2:4} maxLength={10000}
                onChange={e=>updateBlock(i,"text",e.target.value)}/></label>}
              <div className="owner-actions">
                <button disabled={i===0} onClick={()=>moveBlock(i,-1)}>Up</button>
                <button disabled={i===doc.blocks.length-1} onClick={()=>moveBlock(i,1)}>Down</button>
                <button onClick={()=>setDoc(old=>({...old,blocks:old.blocks.filter((_,j)=>j!==i)}))}>Remove</button>
              </div>
            </fieldset>)}
            {chosen&&<button className="button" disabled={busy||!!chosen.trashedAt}
              onClick={()=>void act("/api/owner/pages/"+chosen.id+"/draft",doc,"New draft revision saved.")}>Save new draft revision</button>}
          </div>
          <div className="owner-preview" aria-label="Local unpublished preview">
            <h3>Local preview — unpublished</h3><h2>{doc.title||"Untitled"}</h2>
            <p>{doc.description}</p><PublishedBlocks blocks={doc.blocks}/>
          </div>
        </section>
      </div>
    </div>
  </section>;
}
