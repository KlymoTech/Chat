import {NextResponse} from "next/server";
import {cookies} from "next/headers";
import {CONSENT_COOKIE,parseConsentChoice,recordChoice,mayCollectByReceipt}
  from "../../../../lib/consent-server";
export const dynamic="force-dynamic";
const headers={"Cache-Control":"private, no-store","X-Content-Type-Options":"nosniff"};
const available=()=>process.env.WEBSITE_CONSENT_RECORDS_ENABLED==="true"&&
  process.env.WEBSITE_PRIVACY_DB_GRANTS_VERIFIED==="true";
function safeOrigin(request:Request):boolean {
  const origin=process.env.WEBSITE_CANONICAL_ORIGIN;
  return Boolean(origin && request.headers.get("origin")===origin);
}
export async function GET(){
  if(!available())return NextResponse.json({status:"unavailable",analytics:false,marketing:false},
    {status:503,headers});
  const jar=await cookies();
  const id=jar.get(CONSENT_COOKIE)?.value;
  const analytics=await mayCollectByReceipt(id,"analytics");
  const marketing=await mayCollectByReceipt(id,"marketing");
  return NextResponse.json({status:"recorded",analytics,marketing},{headers});
}
export async function POST(request:Request){
  if(!available())return NextResponse.json({error:"Consent receipt unavailable"},
    {status:503,headers});
  if(!safeOrigin(request))return NextResponse.json({error:"Origin not allowed"},
    {status:403,headers});
  if(request.headers.get("content-type")!=="application/json")
    return NextResponse.json({error:"JSON required"},{status:415,headers});
  if(Number(request.headers.get("content-length")??0)>1024)
    return NextResponse.json({error:"Payload too large"},{status:413,headers});
  let choice;
  try{
    const raw=await request.text();
    if(raw.length>1024)throw new Error("Oversize");
    choice=parseConsentChoice(JSON.parse(raw));
  }catch{return NextResponse.json({error:"Invalid choice"},{status:422,headers});}
  if(!choice)return NextResponse.json({error:"Invalid choice"},{status:422,headers});
  const jar=await cookies();
  try{
    const id=await recordChoice(jar.get(CONSENT_COOKIE)?.value,choice);
    const response=NextResponse.json({status:"recorded",analytics:choice.analytics,
      marketing:choice.marketing},{headers});
    response.cookies.set(CONSENT_COOKIE,id??"",{
      httpOnly:true,sameSite:"lax",
      secure:process.env.NODE_ENV==="production",path:"/",
      maxAge:id?60*60*24*30:0,
    });
    return response;
  }catch{
    return NextResponse.json({error:"Cannot save choice; optional collection remains off"},
      {status:503,headers});
  }
}
