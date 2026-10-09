import {NextResponse} from "next/server";
import {bodyJson,checkMutationRequest,ownerResponse,requireOwner} from "../../../../lib/owner-api";
import {createAutomationDraft,listAutomationDrafts} from "../../../../lib/automation-drafts";
import {validateAutomation} from "../../../../lib/automation-contract";
export const dynamic="force-dynamic";
export async function GET(request:Request) {
  const actor=await requireOwner(request,"cms:automation");
  if(actor instanceof NextResponse)return actor;
  try{return ownerResponse({drafts:await listAutomationDrafts(actor),executionEnabled:false});}
  catch{return ownerResponse({error:"Automation draft listing unavailable"},503);}
}
export async function POST(request:Request) {
  const actor=await requireOwner(request,"cms:automation");
  if(actor instanceof NextResponse)return actor;
  const invalid=checkMutationRequest(request);
  if(invalid)return invalid;
  let body:unknown;
  try{body=await bodyJson(request);}catch{return ownerResponse({error:"Invalid draft body"},422);}
  const definition=validateAutomation(body);
  if(!definition)return ownerResponse({error:"Unsafe or invalid workflow graph"},422);
  try{return ownerResponse(await createAutomationDraft(actor,definition),201);}
  catch{return ownerResponse({error:"Unable to store automation draft"},503);}
}
