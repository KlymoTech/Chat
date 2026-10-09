import {NextResponse} from "next/server";
import {loadPrivateReviewImage} from "../../../../../../../lib/media-review";
import {requireOwner} from "../../../../../../../lib/owner-api";

export const dynamic="force-dynamic";
export const runtime="nodejs";
type Params={params:Promise<{assetId:string}>};
const privateHeaders={
  "Cache-Control":"private, no-store, max-age=0",
  "Content-Type":"image/webp",
  "Content-Disposition":'inline; filename="review-candidate.webp"',
  "X-Content-Type-Options":"nosniff",
  "Content-Security-Policy":"default-src 'none'; sandbox",
};
export async function GET(request:Request,{params}:Params){
  const actor=await requireOwner(request,"cms:media:review");
  if(actor instanceof NextResponse)return actor;
  if(process.env.WEBSITE_MEDIA_REVIEW_ENABLED!=="true"||
     process.env.WEBSITE_MEDIA_REVIEW_DB_ROLE_VERIFIED!=="true")
    return new Response(null,{status:503,headers:{"Cache-Control":"no-store"}});
  const {assetId}=await params;
  try{
    const bytes=await loadPrivateReviewImage(actor,assetId);
    return new Response(new Uint8Array(bytes),{status:200,headers:privateHeaders});
  }catch{
    return new Response(null,{status:404,headers:{
      "Cache-Control":"private, no-store","X-Content-Type-Options":"nosniff",
    }});
  }
}
