#!/usr/bin/env node
/** One-shot trusted batch trigger. No schedule and no customer messaging. */
import {createHmac} from "node:crypto";
const origin=process.env.WEBSITE_CANONICAL_ORIGIN;
const secret=process.env.WEBSITE_AUTOMATION_RUNNER_SECRET;
const local=process.env.NODE_ENV==="development" &&
  process.env.WEBSITE_AUTOMATION_LOCAL_DEV==="true";
let allowedOrigin=null;
try{
  const url=new URL(origin);
  const secure=url.protocol==="https:";
  const loopback=url.protocol==="http:" &&
    (url.hostname==="127.0.0.1"||url.hostname==="localhost");
  const approvedHost=url.hostname.includes(".") &&
    !url.hostname.endsWith(".internal") &&
    !url.hostname.endsWith(".localhost") &&
    !url.hostname.endsWith(".local");
  if((secure&&approvedHost&&url.port==="" || local&&loopback) &&
     !url.username&&!url.password&&!url.search&&!url.hash &&
     url.pathname==="/"){
    allowedOrigin=url.origin;
  }
}catch{}
if(process.env.WEBSITE_AUTOMATION_RUNNER_ENABLED!=="true"||
   process.env.WEBSITE_AUTOMATION_INTERNAL_RUNS_ENABLED!=="true"||
   !secret||secret.length<32||!allowedOrigin){
  console.error("Internal runner is disabled or its local/HTTPS origin is invalid");
  process.exitCode=2;
}else{
  const body='{"operation":"advance-internal"}';
  const timestamp=String(Math.floor(Date.now()/1000));
  const signature=createHmac("sha256",secret).update(timestamp+"."+body).digest("hex");
  try{
    const response=await fetch(new URL("/api/internal/automations/tick",allowedOrigin),{
      method:"POST",redirect:"error",cache:"no-store",
      headers:{"Content-Type":"application/json",
        "X-Automation-Timestamp":timestamp,
        "X-Automation-Signature":"sha256="+signature},
      body,signal:AbortSignal.timeout(30000),
    });
    if(!response.ok)throw Error("Internal batch was not acknowledged");
    const result=await response.json();
    console.log(JSON.stringify(result));
  }catch(error){
    console.error("Internal automation batch unavailable:",error?.message??"error");
    process.exitCode=1;
  }
}
