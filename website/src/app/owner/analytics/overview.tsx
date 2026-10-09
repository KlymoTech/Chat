"use client";
import {useEffect,useState} from "react";
import Link from "next/link";
type Day={day:string;eventName:string;count:number};
export default function AnalyticsOverview(){
  const [days,setDays]=useState<Day[]>([]);
  const [message,setMessage]=useState("Loading consented event summary…");
  useEffect(()=>{
    const abort=new AbortController();
    void fetch("/api/owner/analytics",{cache:"no-store",credentials:"same-origin",signal:abort.signal})
      .then(async response=>{
        if(!response.ok)throw Error("Reporting is not activated or you lack owner access");
        const result:unknown=await response.json();
        if(!result||typeof result!=="object"||!("daily" in result)||
           !Array.isArray(result.daily))throw Error("Invalid report");
        setDays(result.daily as Day[]);
        setMessage("Only site-level groups of five or more events are shown.");
      }).catch(()=>{if(!abort.signal.aborted)setMessage("Report unavailable. No unverified data is displayed.");});
    return ()=>abort.abort();
  },[]);
  return <section className="page" aria-labelledby="analytics-title">
    <p className="eyebrow">Owner reporting · privacy-first</p>
    <h1 id="analytics-title">First-party analytics</h1>
    <p>This report counts optional, consented events received by this website. It does not
      claim unique visitors, true conversions, campaign attribution or CRM outcomes.</p>
    <p><Link href="/owner">Back to owner dashboard</Link></p>
    <p role="status">{message}</p>
    {days.length>0?<div style={{overflowX:"auto"}}><table style={{width:"100%"}}>
      <thead><tr><th scope="col">UTC day</th><th scope="col">Event</th>
        <th scope="col">Count</th></tr></thead>
      <tbody>{days.map(day=><tr key={day.day+day.eventName}>
        <td>{day.day}</td><td>{day.eventName.replaceAll("_"," ")}</td>
        <td>{day.count}</td></tr>)}</tbody>
    </table></div>:<p>No reportable event cohorts yet.</p>}
  </section>;
}
