import {NextResponse} from "next/server";
import {verifyPrivateScanRequest} from "../../../../../lib/media-scan-auth";
import {inspectPrivateMedia} from "../../../../../lib/media-processing";

export const dynamic="force-dynamic";
export const runtime="nodejs";
export const maxDuration=60;
const privateHeaders={"Cache-Control":"private, no-store","X-Content-Type-Options":"nosniff"};

/** Service-to-service only. Never called from a visitor or owner form. */
export async function POST(request:Request) {
  if(process.env.WEBSITE_MEDIA_SCAN_ENABLED!=="true" ||
     process.env.WEBSITE_MEDIA_SCANNER_DB_ROLE_VERIFIED!=="true")
    return NextResponse.json({error:"Scanner disabled"},{status:503,headers:privateHeaders});
  if(request.headers.get("content-type")!=="application/json")
    return NextResponse.json({error:"JSON required"},{status:415,headers:privateHeaders});
  const length=Number(request.headers.get("content-length"));
  if(!Number.isSafeInteger(length)||length<1||length>512)
    return NextResponse.json({error:"Invalid request size"},{status:413,headers:privateHeaders});
  let raw:string;
  try{
    raw=await request.text();
    if(raw.length>512)throw new Error("Oversize");
  }catch{
    return NextResponse.json({error:"Invalid request"},{status:400,headers:privateHeaders});
  }
  const intent=verifyPrivateScanRequest(raw,request.headers,
    process.env.WEBSITE_MEDIA_SCAN_WORKER_SECRET);
  if(!intent)return NextResponse.json({error:"Unauthorized"},{status:401,headers:privateHeaders});
  try {
    const result=await inspectPrivateMedia(intent.siteId,intent.assetId);
    return NextResponse.json({...result,publicAccess:false,approved:false},
      {status:200,headers:privateHeaders});
  }catch{
    return NextResponse.json({error:"Private media scan incomplete; preserve quarantine"},
      {status:503,headers:privateHeaders});
  }
}
