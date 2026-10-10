'use client';
import {FormEvent,useRef,useState} from 'react';
export function LeadForm(){
 const [status,setStatus]=useState<'idle'|'sending'|'sent'|'error'>('idle');
 const [error,setError]=useState('');
 const key=useRef<string|null>(null);
 async function submit(e:FormEvent<HTMLFormElement>){
  e.preventDefault();setStatus('sending');setError('');
  const form=e.currentTarget;
  if(!key.current)key.current=crypto.randomUUID();
  const values=new FormData(form);
  const payload={name:String(values.get('name')||''),email:String(values.get('email')||''),message:String(values.get('message')||''),marketingOptIn:values.get('marketingOptIn')==='on',website:String(values.get('website')||''),idempotencyKey:key.current};
  try{
   const result=await fetch('/api/v1/public/leads',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
   if(!result.ok)throw new Error('The enquiry was not accepted. Please check the fields and try again.');
   const ack=await result.json() as {accepted?:boolean};
   if(!ack.accepted)throw new Error('The server did not confirm acceptance.');
   key.current=null;form.reset();setStatus('sent');
  }catch(e){setError(e instanceof Error?e.message:'Unable to submit. Please retry.');setStatus('error');}
 }
 return <form className="form" onSubmit={submit}>
  <label htmlFor="name">Name *</label><input required id="name" name="name" autoComplete="name" maxLength={120}/>
  <label htmlFor="email">Email *</label><input required id="email" name="email" type="email" autoComplete="email" maxLength={254}/>
  <label htmlFor="message">Your message *</label><textarea required minLength={5} maxLength={4000} id="message" name="message" rows={5}/>
  <div className="honeypot" aria-hidden="true"><label htmlFor="website">Website</label><input tabIndex={-1} id="website" name="website" autoComplete="off"/></div>
  <label className="check"><input type="checkbox" name="marketingOptIn"/> I separately agree to receive optional marketing updates.</label>
  <p className="subtle">Your information is handled according to our <a href="/privacy">privacy notice</a>. The optional checkbox does not affect your enquiry.</p>
  <button className="button" disabled={status==='sending'} type="submit">{status==='sending'?'Sending…':'Send enquiry ↗'}</button>
  <div aria-live="polite" role="status">{status==='sent'&&<p className="success">Your enquiry was saved. Thank you.</p>}{status==='error'&&<p className="error">{error}</p>}</div>
 </form>;
}
