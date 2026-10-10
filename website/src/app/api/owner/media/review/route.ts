import {NextResponse} from "next/server";
import {listMediaForReview,reviewPrivateMedia} from "../../../../../lib/media-review";
import {bodyJson,checkMutationRequest,ownerResponse,requireOwner} from "../../../../../lib/owner-api";

export const dynamic="force-dynamic";
const available=()=>process.env.WEBSITE_MEDIA_REVIEW_ENABLED==="true" &&
  process.env.WEBSITE_MEDIA_REVIEW_DB_ROLE_VERIFIED==="true";

export async function GET(request:Request) {
  const actor=await requireOwner(request,"cms:media:review");
  if(actor instanceof NextResponse)return actor;
  if(!available())return ownerResponse({error:"Independent review disabled"},503);
  try{return ownerResponse({pending:await listMediaForReview(actor)});}
  catch{return ownerResponse({error:"Private review queue unavailable"},503);}
}
export async function POST(request:Request) {
  const actor=await requireOwner(request,"cms:media:review");
  if(actor instanceof NextResponse)return actor;
  if(!available())return ownerResponse({error:"Independent review disabled"},503);
  const invalid=checkMutationRequest(request);
  if(invalid)return invalid;
  let body:unknown;
  try{body=await bodyJson(request);}
  catch{return ownerResponse({error:"Invalid review request"},422);}
  if(!body||typeof body!=="object"||Array.isArray(body))
    return ownerResponse({error:"Invalid review body"},422);
  const fields=body as Record<string,unknown>;
  if(typeof fields.assetId!=="string" ||
     (fields.action!=="approve" && fields.action!=="reject") ||
     (fields.action==="approve" && (typeof fields.reviewedSha256!=="string" ||
       !/^[0-9a-f]{64}$/.test(fields.reviewedSha256))) ||
     typeof fields.reason!=="string" ||
     fields.reason.trim().length<10||fields.reason.trim().length>500)
    return ownerResponse({error:"Review reason and explicit decision required"},422);
  try{
    return ownerResponse(await reviewPrivateMedia(
      actor,fields.assetId,fields.action,fields.reason,
      typeof fields.reviewedSha256==="string"?fields.reviewedSha256:undefined),200);
  }catch{
    return ownerResponse({error:"Cannot review this media; check independence and inspection evidence"},409);
  }
}
