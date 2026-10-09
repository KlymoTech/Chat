import {NextResponse} from "next/server";
import {bodyJson,checkMutationRequest,ownerResponse,requireOwner} from "../../../../../lib/owner-api";
import {decideMediaPublication,listApprovedMedia} from "../../../../../lib/media-publication";

export const dynamic="force-dynamic";
const available=()=>process.env.WEBSITE_MEDIA_PUBLICATION_ENABLED==="true" &&
  process.env.WEBSITE_MEDIA_PUBLISH_DB_ROLE_VERIFIED==="true";

export async function GET(request:Request) {
  const actor=await requireOwner(request,"cms:media:publish");
  if(actor instanceof NextResponse)return actor;
  if(!available())return ownerResponse({error:"Media publication disabled"},503);
  try{return ownerResponse({media:await listApprovedMedia(actor)});}
  catch{return ownerResponse({error:"Approved media index unavailable"},503);}
}
export async function POST(request:Request) {
  const actor=await requireOwner(request,"cms:media:publish");
  if(actor instanceof NextResponse)return actor;
  if(!available())return ownerResponse({error:"Media publication disabled"},503);
  const error=checkMutationRequest(request);
  if(error)return error;
  let data:unknown;
  try{data=await bodyJson(request);}
  catch{return ownerResponse({error:"Invalid request"},422);}
  if(!data||typeof data!=="object"||Array.isArray(data))
    return ownerResponse({error:"Invalid decision"},422);
  const d=data as Record<string,unknown>;
  if(typeof d.assetId!=="string"||
    (d.action!=="publish"&&d.action!=="withdraw")||
    typeof d.reason!=="string"||d.reason.trim().length<10||d.reason.trim().length>500)
    return ownerResponse({error:"Explicit decision and justification required"},422);
  if(d.action==="withdraw" && d.impactAcknowledged!==true &&
     d.impactAcknowledged!==false)
    return ownerResponse({error:"Withdrawal impact acknowledgement is required"},422);
  try{return ownerResponse(await decideMediaPublication(
    actor,d.assetId,d.action,d.reason,d.impactAcknowledged===true));}
  catch{return ownerResponse({error:"Publication state or permissions do not permit this action"},409);}
}
