import {NextResponse} from "next/server";
import {requireOwner,ownerResponse,checkMutationRequest,bodyJson}
  from "../../../../lib/owner-api";
import {createRedirectDraft,listOwnerRedirects} from "../../../../lib/content-redirects";
import {parseRedirectDraft} from "../../../../lib/redirect-contract";
export const dynamic="force-dynamic";
export async function GET(request:Request){
  const actor=await requireOwner(request,"cms:redirect");
  if(actor instanceof NextResponse)return actor;
  try{return ownerResponse({redirects:await listOwnerRedirects(actor)});}
  catch{return ownerResponse({error:"Redirect registry disabled or unavailable"},503);}
}
export async function POST(request:Request){
  const actor=await requireOwner(request,"cms:redirect");
  if(actor instanceof NextResponse)return actor;
  const invalid=checkMutationRequest(request);
  if(invalid)return invalid;
  let body:unknown;
  try{body=await bodyJson(request);}
  catch{return ownerResponse({error:"Invalid request body"},422);}
  const draft=parseRedirectDraft(body);
  if(!draft)return ownerResponse({error:"Invalid internal redirect"},422);
  try{return ownerResponse(await createRedirectDraft(actor,draft),201);}
  catch{return ownerResponse({error:"Redirect already registered or storage unavailable"},409);}
}
