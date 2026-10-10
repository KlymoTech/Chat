"use client";

import { useEffect, useState } from "react";

export const CONSENT_KEY = "website-consent-v1";
export type ConsentChoices = { analytics: boolean; marketing: boolean; savedAt: string; version: 1 };
export const CONSENT_CHANGE_EVENT = "website:consent-changed";

function readChoices(): ConsentChoices | null {
  try {
    const value = window.localStorage.getItem(CONSENT_KEY);
    if (!value) return null;
    const parsed: unknown = JSON.parse(value);
    if (!parsed || typeof parsed !== "object") return null;
    const p = parsed as Record<string, unknown>;
    return p.version === 1 && typeof p.analytics === "boolean" && typeof p.marketing === "boolean" &&
      typeof p.savedAt === "string" &&
      Number.isFinite(Date.parse(p.savedAt)) &&
      Date.now()-Date.parse(p.savedAt)>=0 &&
      Date.now()-Date.parse(p.savedAt)<30*24*60*60*1000
      ? { analytics: p.analytics, marketing: p.marketing, savedAt: p.savedAt, version: 1 } : null;
  } catch {
    return null;
  }
}

function browserGpc():boolean {
  try{return (navigator as Navigator&{globalPrivacyControl?:boolean}).globalPrivacyControl===true;}
  catch{return false;}
}
/** Deny all optional purposes if storage is unavailable or consent is unknown. */
export function currentConsent(): Pick<ConsentChoices, "analytics" | "marketing"> {
  if (typeof window === "undefined") return { analytics: false, marketing: false };
  const value = readChoices();
  return { analytics: Boolean(value?.analytics), marketing: Boolean(value?.marketing)&&!browserGpc() };
}

export function ConsentPreferences() {
  const [open, setOpen] = useState(false);
  const [decided, setDecided] = useState(true);
  const [analytics, setAnalytics] = useState(false);
  const [marketing, setMarketing] = useState(false);
  const [notice, setNotice] = useState("");
  const [gpc,setGpc] = useState(false);

  useEffect(() => {
    const sync=()=>{
      const saved=readChoices();
      const blocked=browserGpc();setGpc(blocked);
      setDecided(Boolean(saved));
      setAnalytics(Boolean(saved?.analytics));
      setMarketing(Boolean(saved?.marketing)&&!blocked);
    };
    sync();
    window.addEventListener("storage",sync);
    window.addEventListener(CONSENT_CHANGE_EVENT,sync);
    return ()=>{window.removeEventListener("storage",sync);
      window.removeEventListener(CONSENT_CHANGE_EVENT,sync);};
  }, []);

  async function save(nextAnalytics: boolean, nextMarketing: boolean) {
    let recorded=false;
    let allowedAnalytics=false;
    let allowedMarketing=false;
    try {
      const response=await fetch("/api/privacy/choices",{
        method:"POST",cache:"no-store",credentials:"same-origin",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({analytics:nextAnalytics,marketing:nextMarketing&&!browserGpc()}),
      });
      if(response.ok){
        const payload:unknown=await response.json();
        if(payload&&typeof payload==="object"&&
           "status" in payload&&payload.status==="recorded"&&
           "analytics" in payload&&typeof payload.analytics==="boolean"&&
           "marketing" in payload&&typeof payload.marketing==="boolean"){
          recorded=true;
          allowedAnalytics=payload.analytics;
          allowedMarketing=payload.marketing&&!browserGpc();
        }
      }
    }catch{/* Server unreachable: never infer permission. */}
    // Use the *effective server-confirmed* optional permissions, not the request.
    const choices:ConsentChoices={
      analytics:allowedAnalytics,marketing:allowedMarketing,
      savedAt:new Date().toISOString(),version:1,
    };
    try{
      window.localStorage.setItem(CONSENT_KEY,JSON.stringify(choices));
      window.dispatchEvent(new CustomEvent(CONSENT_CHANGE_EVENT,{detail:choices}));
      setAnalytics(allowedAnalytics);setMarketing(allowedMarketing);
      setDecided(true);setOpen(false);
      setNotice(recorded?"Your privacy choices are saved.":
        "The server could not confirm this choice. Optional browser tracking remains off. Please retry to confirm a withdrawal on the server.");
    }catch{
      setDecided(false);setOpen(false);
      window.dispatchEvent(new CustomEvent(CONSENT_CHANGE_EVENT,{
        detail:{analytics:false,marketing:false,savedAt:"",version:1},
      }));
      setNotice("Preferences could not be saved on this device. Optional browser tracking stays off.");
    }
  }

  return <>
    <button className="privacy-settings-link" type="button" onClick={() => {setOpen(true);setNotice("");}}>
      Privacy choices
    </button>
    {!decided && !open && <section className="consent-notice" aria-label="Privacy choices" role="region">
      <p>Optional analytics and marketing technologies are off unless you choose to allow them. Essential site functionality remains available.</p>
      <div className="consent-actions">
        <button type="button" className="button secondary" onClick={() => save(false, false)}>Reject optional</button>
        <button type="button" className="button secondary" onClick={() => setOpen(true)}>Manage choices</button>
        <button type="button" className="button" onClick={() => save(true, !gpc)}>Accept available optional</button>
      </div>
    </section>}
    {open && <section className="consent-notice" role="region" aria-label="Manage privacy choices">
      <h2>Privacy preferences</h2>
      <p>Essential operations are always enabled. Optional tracking is not loaded by this starter website.</p>
      <label className="consent-toggle"><input type="checkbox" checked={analytics}
        onChange={event => setAnalytics(event.target.checked)} /> Analytics (optional)</label>
      <label className="consent-toggle"><input type="checkbox" checked={marketing&&!gpc}
        disabled={gpc} onChange={event => setMarketing(event.target.checked)} /> Marketing measurement (optional)</label>
      {gpc&&<p role="status">Global Privacy Control is active in this browser. Optional marketing measurement remains off.</p>}
      <div className="consent-actions">
        <button type="button" className="button secondary" onClick={() => save(false, false)}>Reject optional</button>
        <button type="button" className="button" onClick={() => save(analytics, marketing)}>Save my choices</button>
        <button type="button" className="button secondary" onClick={() => setOpen(false)}>Close</button>
      </div>
    </section>}
    {notice&&<p className="consent-feedback" role="status" aria-live="polite">{notice}</p>}
  </>;
}
