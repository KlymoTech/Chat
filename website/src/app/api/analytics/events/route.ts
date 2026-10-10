import {NextResponse} from "next/server";
import {cookies} from "next/headers";
import {CONSENT_COOKIE} from "../../../../lib/consent-server";
import {parseAnalyticsEvent} from "../../../../lib/analytics-contract";
import {recordOptionalAnalytics} from "../../../../lib/analytics-server";
export const dynamic="force-dynamic";
const headers={"Cache-Control":"private, no-store","X-Content-Type-Options":"nosniff"};
/** Optional first-party anonymous event. No attribution IDs, form values, URLs or IP. */
export async function POST(request:Request){
  if(process.env.WEBSITE_ANALYTICS_COLLECTION_ENABLED!=="true")
    return new Response(null,{status:204,headers});
  if(!process.env.WEBSITE_CANONICAL_ORIGIN||
     request.headers.get("origin")!==process.env.WEBSITE_CANONICAL_ORIGIN)
    return NextResponse.json({error:"Origin denied"},{status:403,headers});
  if(request.headers.get("content-type")!=="application/json")
    return NextResponse.json({error:"JSON required"},{status:415,headers});
  const length=Number(request.headers.get("content-length")??0);
  if(!Number.isSafeInteger(length)||length>1024||length<0)
    return NextResponse.json({error:"Too large"},{status:413,headers});
  let event;
  try{
    const raw=await request.text();
    if(raw.length>1024)throw Error("Too large");
    event=parseAnalyticsEvent(JSON.parse(raw));
  }catch{return NextResponse.json({error:"Invalid event"},{status:422,headers});}
  if(!event)return NextResponse.json({error:"Event not allowed"},{status:422,headers});
  const jar=await cookies();
  const recorded=await recordOptionalAnalytics(jar.get(CONSENT_COOKIE)?.value,event);
  // No false success response: suppressed/refused events receive 202.
  return new Response(null,{status:recorded?204:202,headers});
}
