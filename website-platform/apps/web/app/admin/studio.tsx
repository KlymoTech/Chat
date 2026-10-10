'use client';
import {useCallback,useEffect,useState} from 'react';
import Link from 'next/link';
import {useRouter} from 'next/navigation';
type Kind='pages'|'articles';
type Tab='overview'|Kind|'leads'|'settings'|'audit';
type Doc={id:string;title:string;slug:string;description:string;body:string;status:string;revision:number;draftVersion:number;updatedAt:string};
type Lead={id:string;name:string;email:string;message:string;status:string;createdAt:string};
type Site={name:string;tagline:string;description:string};
type Summary={pages:number;articles:number;leads:number;pendingJobs:number};
type Audit={id:string;action:string;entity:string;entityId:string;createdAt:string};
type Outbox={id:string;topic:string;state:string;createdAt:string};
type Draft={id?:string;title:string;slug:string;description:string;body:string;revision?:number;draftVersion?:number;status?:string};
const empty:Draft={title:'',slug:'',description:'',body:''};
async function call<T>(path:string,method='GET',body?:unknown):Promise<T>{
 const response=await fetch('/api/v1/'+path,{method,credentials:'same-origin',headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});
 if(response.status===401)throw new Error('AUTH');
 if(!response.ok){const payload=await response.json().catch(()=>null) as {message?:string|string[]}|null;throw new Error(Array.isArray(payload?.message)?payload.message.join(', '):payload?.message||('Request failed: '+response.status));}
 return response.json() as Promise<T>;
}
export function Studio(){
 const router=useRouter();
 const [tab,setTab]=useState<Tab>('overview'),[error,setError]=useState(''),[info,setInfo]=useState(''),[loading,setLoading]=useState(true),[saving,setSaving]=useState(false);
 const [summary,setSummary]=useState<Summary>({pages:0,articles:0,leads:0,pendingJobs:0});
 const [site,setSite]=useState<Site>({name:'',tagline:'',description:''});
 const [pages,setPages]=useState<Doc[]>([]),[articles,setArticles]=useState<Doc[]>([]),[leads,setLeads]=useState<Lead[]>([]),[audit,setAudit]=useState<Audit[]>([]),[outbox,setOutbox]=useState<Outbox[]>([]);
 const [draft,setDraft]=useState<Draft|null>(null);
 const reload=useCallback(async()=>{
  try{
   const [s,st,p,a,l,log,q]=await Promise.all([
    call<Summary>('admin/summary'),call<Site>('admin/site'),call<Doc[]>('admin/pages'),call<Doc[]>('admin/articles'),call<Lead[]>('admin/leads'),call<Audit[]>('admin/audit'),call<Outbox[]>('admin/outbox')
   ]);
   setSummary(s);setSite(st);setPages(p);setArticles(a);setLeads(l);setAudit(log);setOutbox(q);
  }catch(e){if(e instanceof Error&&e.message==='AUTH')router.replace('/admin/login');else setError(e instanceof Error?e.message:'Could not load console');}
  finally{setLoading(false);}
 },[router]);
 useEffect(()=>{void reload();},[reload]);
 function changeTab(next:Tab){setTab(next);setDraft(null);setInfo('');setError('');}
 function updateDraft(field:'title'|'slug'|'description'|'body',value:string){setDraft(p=>p?{...p,[field]:value}:p);}
 async function run(fn:()=>Promise<void>){
  setSaving(true);setError('');setInfo('');
  try{await fn();await reload();}catch(e){if(e instanceof Error&&e.message==='AUTH')router.replace('/admin/login');else setError(e instanceof Error?e.message:'Operation failed');}
  finally{setSaving(false);}
 }
 async function saveDocument(){
  if(!draft || (tab!=='pages'&&tab!=='articles'))return;
  const kind=tab,current=draft;
  await run(async()=>{
   const path='admin/'+kind+(current.id?'/'+current.id:'');
   const saved=await call<Doc>(path,current.id?'PATCH':'POST',{title:current.title,slug:current.slug,description:current.description,body:current.body,...(current.id?{revision:current.draftVersion}: {})});
   setDraft(saved);setInfo(current.id?'Draft saved. Public version unchanged until you publish.':'New draft created.');
  });
 }
 async function publishDocument(){
  if(!draft?.id || (tab!=='pages'&&tab!=='articles'))return;
  await run(async()=>{
   const result=await call<Doc>('admin/'+tab+'/'+draft.id+'/publish','POST');
   setDraft(result);setInfo('Published. Your changes are now eligible for public display.');
  });
 }
 async function saveSite(){await run(async()=>{await call('admin/site','PATCH',site);setInfo('Site information saved.');});}
 async function setLeadStatus(id:string,status:string){await run(async()=>{await call('admin/leads/'+id,'PATCH',{status});setInfo('Lead status updated.');});}
 async function logout(){await run(async()=>{await call('auth/logout','POST');router.replace('/admin/login');});}
 if(loading)return <div className="studio-panel"><h1>Loading owner console…</h1><p>Checking your session.</p></div>;
 const current=tab==='pages'?pages:articles;
 return <div className="studio">
  <aside className="studio-sidebar"><p className="eyebrow">Website Studio</p><nav aria-label="Owner console sections">
   {(['overview','pages','articles','leads','settings','audit'] as const).map(item=><button key={item} className={tab===item?'active':''} onClick={()=>changeTab(item)} type="button">{({overview:'Overview',pages:'Pages',articles:'Articles',leads:'Leads',settings:'Site settings',audit:'Audit & queue'})[item]}</button>)}
   </nav><button onClick={()=>void logout()} type="button">Sign out</button></aside>
  <div className="studio-main"><div className="studio-panel"><p className="eyebrow">Owner workspace</p><h1 style={{fontSize:'2.3rem',margin:0}}>{({overview:'Overview',pages:'Pages',articles:'Articles',leads:'Leads',settings:'Site settings',audit:'Audit & delivery'})[tab]}</h1><p className="subtle">Edits are saved as drafts; published revisions are recorded separately.</p>
   {error&&<p className="error" role="alert">{error}</p>}{info&&<p className="success" role="status">{info}</p>}
  </div>
  {tab==='overview'&&<><div className="metrics"><div className="metric"><strong>{summary.pages}</strong>Pages</div><div className="metric"><strong>{summary.articles}</strong>Articles</div><div className="metric"><strong>{summary.leads}</strong>Leads</div><div className="metric"><strong>{summary.pendingJobs}</strong>Pending delivery events</div></div><div className="studio-panel"><h2>Website operations</h2><p>Public content is served from approved published revisions. Marketing integrations remain disabled until their prerequisites are reviewed.</p><p><Link href="/" target="_blank">Open public website ↗</Link></p></div></>}
  {(tab==='pages'||tab==='articles')&&<div className="studio-panel"><div className="studio-controls"><button className="primary" disabled={saving} onClick={()=>setDraft({...empty})} type="button">+ New {tab==='pages'?'page':'article'}</button><button onClick={()=>void reload()} type="button">Refresh</button></div>
   {!draft&&<div>{current.length===0?<p>No content yet. Create the first draft.</p>:current.map(item=><div className="list-row" key={item.id}><div><strong>{item.title}</strong><p className="subtle">/{tab==='articles'?'blog/':''}{item.slug} · <span className="status">{item.status}</span> · revision {item.revision}</p></div><button type="button" onClick={()=>setDraft(item)}>Edit draft →</button></div>)}</div>}
   {draft&&<div><div className="studio-controls"><button onClick={()=>setDraft(null)} type="button">← Back to list</button></div><div className="field"><label htmlFor="doc-title">Title</label><input id="doc-title" value={draft.title} maxLength={160} onChange={e=>updateDraft('title',e.target.value)}/></div>
    <div className="field"><label htmlFor="doc-slug">URL slug</label><input id="doc-slug" value={draft.slug} maxLength={80} pattern="[a-z0-9]+(-[a-z0-9]+)*" onChange={e=>updateDraft('slug',e.target.value)}/><p className="subtle">Published URL slugs cannot be renamed without a redirect workflow.</p></div>
    <div className="field"><label htmlFor="doc-desc">Search description</label><textarea id="doc-desc" maxLength={300} value={draft.description} onChange={e=>updateDraft('description',e.target.value)}/></div>
    <div className="field"><label htmlFor="doc-body">Body (plain text)</label><textarea id="doc-body" rows={12} value={draft.body} onChange={e=>updateDraft('body',e.target.value)}/></div>
    <div className="studio-controls"><button type="button" className="primary" disabled={saving||!draft.title||!draft.slug} onClick={()=>void saveDocument()}>Save draft</button>{draft.id&&<button type="button" disabled={saving} onClick={()=>void publishDocument()}>Publish current saved draft</button>}</div>
    <div className="studio-panel"><p className="eyebrow">Local preview · not public</p><h2>{draft.title||'Untitled'}</h2><p>{draft.description}</p><div className="prose">{draft.body}</div></div>
   </div>}
  </div>}
  {tab==='leads'&&<div className="studio-panel"><h2>Recent enquiries</h2><p className="subtle">Limited to the most recent 100 accepted enquiries.</p>{leads.length===0?<p>No submissions yet.</p>:leads.map(l=><div key={l.id} className="list-row"><div><strong>{l.name}</strong><p><a href={'mailto:'+l.email}>{l.email}</a></p><p>{l.message}</p><small>{new Date(l.createdAt).toLocaleString()}</small></div><label>Status <select value={l.status} disabled={saving} onChange={e=>void setLeadStatus(l.id,e.target.value)}>{['NEW','CONTACTED','QUALIFIED','CLOSED'].map(v=><option key={v}>{v}</option>)}</select></label></div>)}</div>}
  {tab==='settings'&&<div className="studio-panel"><h2>Public identity</h2><div className="field"><label htmlFor="site-name">Business name</label><input id="site-name" value={site.name} maxLength={120} onChange={e=>setSite(s=>({...s,name:e.target.value}))}/></div><div className="field"><label htmlFor="site-tagline">Tagline</label><input id="site-tagline" value={site.tagline} maxLength={240} onChange={e=>setSite(s=>({...s,tagline:e.target.value}))}/></div><div className="field"><label htmlFor="site-description">Description</label><textarea id="site-description" value={site.description} onChange={e=>setSite(s=>({...s,description:e.target.value}))}/></div><button type="button" className="button" disabled={saving} onClick={()=>void saveSite()}>Save site settings</button></div>}
  {tab==='audit'&&<><div className="studio-panel"><h2>Recent audit trail</h2><div className="table-wrap"><table><thead><tr><th>Time</th><th>Action</th><th>Entity</th></tr></thead><tbody>{audit.map(a=><tr key={a.id}><td>{new Date(a.createdAt).toLocaleString()}</td><td>{a.action}</td><td>{a.entity}</td></tr>)}</tbody></table></div></div><div className="studio-panel"><h2>Outbox events</h2><p className="subtle">PENDING means external delivery and downstream effects have not been acknowledged.</p><div className="table-wrap"><table><thead><tr><th>Time</th><th>Topic</th><th>State</th></tr></thead><tbody>{outbox.map(e=><tr key={e.id}><td>{new Date(e.createdAt).toLocaleString()}</td><td>{e.topic}</td><td>{e.state}</td></tr>)}</tbody></table></div></div></>}
  </div></div>;
}
