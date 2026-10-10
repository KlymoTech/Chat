import {NextResponse} from "next/server";
import {requireOwner,ownerResponse,checkMutationRequest,bodyJson}
  from "../../../../../../lib/owner-api";
import {advanceRightsCase} from "../../../../../../lib/privacy-rights-service";
import {validCaseState,CASE_REASONS,type CaseReason}
  from "../../../../../../lib/privacy-rights-contract";
export const dynamic="force-dynamic";
export async function POST(request:Request,{params}:{
  params:Promise<{id:string}>
}){
  const actor=await requireOwner(request,"cms:privacy");
  if(actor instanceof NextResponse)return actor;
  const invalid=checkMutationRequest(request);
  if(invalid)return invalid;
  let raw:unknown;
  try{raw=await bodyJson(request);}
  catch{return ownerResponse({error:"Invalid transition body"},422);}
  if(!raw||typeof raw!=="object"||Array.isArray(raw))
    return ownerResponse({error:"Invalid transition"},422);
  const v=raw as Record<string,unknown>;
  if(Object.keys(v).some(k=>!["expectedRevision","to","reason","evidenceRef"].includes(k))||
     !Number.isSafeInteger(v.expectedRevision)||Number(v.expectedRevision)<1||
     !validCaseState(v.to)||typeof v.reason!=="string"||
     !CASE_REASONS.some(reason=>reason===v.reason)||
     (v.evidenceRef!==undefined&&typeof v.evidenceRef!=="string"))
    return ownerResponse({error:"Invalid rights transition"},422);
  try{
    return ownerResponse(await advanceRightsCase(actor,(await params).id,
      v.expectedRevision as number,v.to,v.reason as CaseReason,
      v.evidenceRef as string|undefined));
  }catch(error){
    if(error instanceof Error && error.message.includes("revision conflict"))
      return ownerResponse({error:"Case changed. Refresh before deciding."},409);
    return ownerResponse({error:"Rights case transition denied or unavailable"},409);
  }
}
