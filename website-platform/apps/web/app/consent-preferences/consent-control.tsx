'use client';
import {useEffect,useState} from 'react';
export function ConsentControl(){
 const [allow,setAllow]=useState(false),[saved,setSaved]=useState(false);
 useEffect(()=>setAllow(document.cookie.split(';').map(x=>x.trim()).includes('marketing_preference=yes')),[]);
 function save(){document.cookie='marketing_preference='+(allow?'yes':'no')+'; Path=/; Max-Age=15552000; SameSite=Lax'+(location.protocol==='https:'?'; Secure':'');setSaved(true);}
 return <div className="contact-card"><label className="check"><input type="checkbox" checked={allow} onChange={e=>{setAllow(e.target.checked);setSaved(false);}}/> Remember my optional marketing preference</label><p className="subtle">This preference does not subscribe you or turn on any analytics; the enquiry form requires its own explicit choice.</p><button className="button" onClick={save} type="button">Save preference</button>{saved&&<p role="status" className="success">Saved for this browser.</p>}</div>;
}
