import {NextResponse} from "next/server";
import {verifyInternalTick} from "../../../../../lib/internal-automation-auth";
import {advanceDueInternalAutomations} from "../../../../../lib/internal-automation-runs";
export const dynamic="force-dynamic";
export const runtime="nodejs";
export const maxDuration=30;
const headers={"Cache-Control":"private, no-store","X-Content-Type-Options":"nosniff"};
export async function POST(request:Request){
  if(process.env.WEBSITE_AUTOMATION_RUNNER_ENABLED!=="true"||
     process.env.WEBSITE_AUTOMATION_INTERNAL_RUNS_ENABLED!=="true"||
     process.env.WEBSITE_AUTOMATION_RUN_DB_ROLE_VERIFIED!=="true")
    return NextResponse.json({error:"Runner disabled"},{status:503,headers});
  if(request.headers.get("content-type")!=="application/json")
    return NextResponse.json({error:"JSON required"},{status:415,headers});
  if(Number(request.headers.get("content-length")??0)>128)
    return NextResponse.json({error:"Invalid payload length"},{status:413,headers});
  let raw="";
  try{raw=await request.text();if(raw.length>128)throw Error("too large");}
  catch{return NextResponse.json({error:"Malformed request"},{status:422,headers});}
  if(!verifyInternalTick(raw,request.headers,
    process.env.WEBSITE_AUTOMATION_RUNNER_SECRET))
    return NextResponse.json({error:"Unauthorized"},{status:401,headers});
  try{return NextResponse.json({
    ...await advanceDueInternalAutomations(),externalMessagesSent:0,
  },{headers});}
  catch{return NextResponse.json({error:"Internal run batch unavailable"},
    {status:503,headers});}
}
