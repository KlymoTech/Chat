import {NextResponse} from "next/server";
import {requireOwner,ownerResponse,checkMutationRequest,bodyJson}
  from "../../../../../../lib/owner-api";
import {reviewRedirect} from "../../../../../../lib/content-redirects";
export const dynamic="force-dynamic";
export async function POST(request:Request,{params}:{
  params:Promise<{id:string;action:string}>
}){
  const actor=await requireOwner(request,"cms:redirect");
  if(actor instanceof NextResponse)return actor;
  const invalid=checkMutationRequest(request);
  if(invalid)return invalid;
  const {id,action}=await params;
  if(action!=="approve"&&action!=="suspend")
    return ownerResponse({error:"Unsupported action"},404);
  let body:unknown;
  try{body=await bodyJson(request);}
  catch{return ownerResponse({error:"Invalid request"},422);}
  if(!body||typeof body!=="object"||Array.isArray(body)||
    Object.keys(body).length!==0)
    return ownerResponse({error:"No unreviewed parameters allowed"},422);
  try{return ownerResponse(await reviewRedirect(actor,id,action));}
  catch(error){
    if(error instanceof Error&&error.message.includes("Independent reviewer"))
      return ownerResponse({error:"A different authorized reviewer is required"},403);
    return ownerResponse({error:"Approval requirements failed or redirect changed"},409);
  }
}
