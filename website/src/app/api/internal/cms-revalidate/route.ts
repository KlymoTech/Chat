import { revalidatePath } from "next/cache";
import { NextResponse } from "next/server";
import { verifyCmsInvalidation } from "../../../../../scripts/cms-invalidation-contract.mjs";

export const dynamic = "force-dynamic";
const headers={"Cache-Control":"no-store, private","X-Content-Type-Options":"nosniff"};

/** Internal, HMAC-authenticated invalidation. Never accept arbitrary paths. */
export async function POST(request: Request) {
  const secret=process.env.WEBSITE_CMS_REVALIDATION_SECRET;
  if(process.env.WEBSITE_CMS_REVALIDATION_ENABLED!=="true" ||
    !secret || secret.length<32) {
    return NextResponse.json({error:"Unavailable"},{status:503,headers});
  }
  if(!(request.headers.get("content-type")??"").startsWith("application/json")) {
    return NextResponse.json({error:"JSON required"},{status:415,headers});
  }
  const length=Number(request.headers.get("content-length")??0);
  if(!Number.isFinite(length)||length<0||length>4096) {
    return NextResponse.json({error:"Payload too large"},{status:413,headers});
  }
  let raw:string;
  try {raw=await request.text();}catch {
    return NextResponse.json({error:"Invalid request"},{status:400,headers});
  }
  const event=verifyCmsInvalidation(raw,request.headers,secret);
  if(!event) {
    return NextResponse.json({error:"Unauthorized"},{status:401,headers});
  }
  try {
    revalidatePath(event.path);
    revalidatePath("/resources");
    revalidatePath("/blog");
    revalidatePath("/sitemap.xml");
    return new NextResponse(null,{status:204,headers});
  } catch {
    // The sender MUST retry; no false acknowledgement of cache reconciliation.
    return NextResponse.json({error:"Unable to invalidate"},{status:503,headers});
  }
}
