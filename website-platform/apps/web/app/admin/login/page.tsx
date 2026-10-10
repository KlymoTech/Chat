'use client';
import {FormEvent,useState} from 'react';
import {useRouter} from 'next/navigation';
export default function Login(){
 const router=useRouter();
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 async function submit(e:FormEvent<HTMLFormElement>){
  e.preventDefault();setError('');setBusy(true);
  const data=new FormData(e.currentTarget);
  try{
   const res=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:data.get('email'),password:data.get('password')})});
   if(!res.ok)throw new Error('Sign-in failed. Check your credentials.');
   router.replace('/admin');router.refresh();
  }catch(e){setError(e instanceof Error?e.message:'Unable to sign in');}finally{setBusy(false);}
 }
 return <section className="admin-layout"><div className="shell narrow"><div className="contact-card">
  <p className="eyebrow">Private area</p><h1 style={{fontSize:'2.5rem'}}>Owner sign-in</h1>
  <form className="form" onSubmit={submit}>
   <label htmlFor="login-email">Email</label><input id="login-email" name="email" autoComplete="username" type="email" required/>
   <label htmlFor="login-password">Password</label><input id="login-password" name="password" autoComplete="current-password" type="password" required/>
   <button className="button" type="submit" disabled={busy}>{busy?'Signing in…':'Sign in →'}</button>
   {error&&<p className="error" role="alert">{error}</p>}
  </form><p className="subtle">Authorized staff only. Sessions are stored in secure, HttpOnly cookies in production.</p>
 </div></div></section>;
}
