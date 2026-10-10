import {NextResponse} from "next/server";
import {requireOwner,ownerResponse,checkMutationRequest,bodyJson}
  from "../../../../../lib/owner-api";
import {listRightsCases,openRightsCase}
  from "../../../../../lib/privacy-rights-service";
import {validCaseKind} from "../../../../../lib/privacy-rights-contract";
export const dynamic="force-dynamic";
export async function GET(request:Request){
  const actor=await requireOwner(request,"cms:privacy");
  if(actor instanceof NextResponse)return actor;
  try{return ownerResponse({cases:await listRightsCases(actor),automaticErasure:false});}
  catch{return ownerResponse({error:"Privacy case management disabled"},503);}
}
export async function POST(request:Request){
  const actor=await requireOwner(request,"cms:privacy");
  if(actor instanceof NextResponse)return actor;
  const invalid=checkMutationRequest(request);
  if(invalid)return invalid;
  let raw:unknown;
  try{raw=await bodyJson(request);}
  catch{return ownerResponse({error:"Invalid request"},422);}
  if(!raw||typeof raw!=="object"||Array.isArray(raw))
    return ownerResponse({error:"Invalid case kind"},422);
  const x=raw as Record<string,unknown>;
  if(Object.keys(x).length!==1||!validCaseKind(x.kind))
    return ownerResponse({error:"Only approved request kinds can be stored"},422);
  try{return ownerResponse(await openRightsCase(actor,x.kind),201);}
  catch{return ownerResponse({error:"Unable to record rights case"},503);}
}
