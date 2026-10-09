"use client";
import { useState, type FormEvent } from "react";
export function EnquiryForm({ fallbackEmail }: { fallbackEmail: string }) {
  const [fullName,setFullName]=useState("");
  const [email,setEmail]=useState("");
  const [message,setMessage]=useState("");
  const [agreed,setAgreed]=useState(false);
  const [idempotencyKey,setIdempotencyKey]=useState("");
  const [status,setStatus]=useState<"idle"|"sending"|"accepted"|"error">("idle");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if(!agreed) return;
    setStatus("sending");
    const key = idempotencyKey || crypto.randomUUID();
    setIdempotencyKey(key);
    try {
      const response=await fetch("/api/leads",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({fullName,email,message,privacyAcknowledged:agreed,idempotencyKey:key})});
      if(!response.ok) throw new Error("Save failed");
      const receipt:unknown=await response.json();
      if(!receipt || typeof receipt!=="object" || !("accepted" in receipt) || receipt.accepted!==true) throw new Error("No receipt");
      setStatus("accepted");
    } catch { setStatus("error"); }
  }
  if(status==="accepted") return <p role="status">Your enquiry has been received and saved. Thank you.</p>;
  return <form onSubmit={submit} className="enquiry-form">
    <label htmlFor="enquiry-name">Full name</label>
    <input id="enquiry-name" name="name" autoComplete="name" maxLength={160} required value={fullName} onChange={e=>{setFullName(e.target.value);setIdempotencyKey("");}}/>
    <label htmlFor="enquiry-email">Email</label>
    <input id="enquiry-email" type="email" autoComplete="email" required maxLength={254} value={email} onChange={e=>{setEmail(e.target.value);setIdempotencyKey("");}}/>
    <label htmlFor="enquiry-message">Your enquiry</label>
    <textarea id="enquiry-message" required maxLength={4000} rows={5} value={message} onChange={e=>{setMessage(e.target.value);setIdempotencyKey("");}}/>
    <label><input type="checkbox" checked={agreed} onChange={e=>setAgreed(e.target.checked)} required/> I acknowledge that this enquiry will be processed to respond to my request.</label>
    <button type="submit" className="button" disabled={status==="sending"}>{status==="sending"?"Saving…":"Send enquiry"}</button>
    {status==="error" && <p role="alert">We could not confirm your enquiry was saved. Retry, or {fallbackEmail ? <a href={`mailto:${fallbackEmail}`}>email us directly</a> : "contact us through another available channel"}.</p>}
  </form>;
}
