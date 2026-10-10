"use client";
import Link from "next/link";
import {currentConsent} from "./ConsentPreferences";
import {parseAnalyticsEvent,type EventName} from "../lib/analytics-contract";

export function optionalTrack(eventName:EventName,actionKey:string):void {
  if(typeof window==="undefined"||!currentConsent().analytics)return;
  const event=parseAnalyticsEvent({eventName,actionKey,routePath:window.location.pathname});
  if(!event)return;
  // No user identifiers, UTM params, form field values, or raw browser location.
  void fetch("/api/analytics/events",{
    method:"POST",credentials:"same-origin",keepalive:true,
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify(event),
  }).catch(()=>{/* Analytics must never block essential navigation. */});
}
export function MeasuredActionLink({href,actionKey,children,className}:{
  href:string;actionKey:string;children:React.ReactNode;className?:string;
}){
  return <Link href={href} className={className}
    onClick={()=>optionalTrack("cta_click",actionKey)}>{children}</Link>;
}
export function MeasuredFaq({question,answer,actionKey}:{
  question:string;answer:string;actionKey:string;
}){
  return <details onToggle={event=>{
    if(event.currentTarget.open)optionalTrack("faq_open",actionKey);
  }}>
    <summary>{question}</summary><p>{answer}</p>
  </details>;
}
