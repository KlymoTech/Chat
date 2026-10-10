import {NextResponse} from "next/server";
import {requireOwner,ownerResponse,bodyJson,checkMutationRequest}
  from "../../../../../../lib/owner-api";
import {listInternalAutomationTasks,completeInternalAutomationTask}
  from "../../../../../../lib/internal-automation-runs";
export const dynamic="force-dynamic";
type Params={params:Promise<{id:string}>};
export async function GET(request:Request,{params}:Params){
  const actor=await requireOwner(request,"cms:automation");
  if(actor instanceof NextResponse)return actor;
  try{return ownerResponse({tasks:await listInternalAutomationTasks(
    actor,(await params).id)});}
  catch{return ownerResponse({error:"Internal task list unavailable"},503);}
}
export async function POST(request:Request,{params}:Params){
  const actor=await requireOwner(request,"cms:automation");
  if(actor instanceof NextResponse)return actor;
  const invalid=checkMutationRequest(request);
  if(invalid)return invalid;
  let body:unknown;
  try{body=await bodyJson(request);}
  catch{return ownerResponse({error:"Invalid task request"},422);}
  if(!body||typeof body!=="object"||Array.isArray(body))
    return ownerResponse({error:"Task and reason required"},422);
  const fields=body as Record<string,unknown>;
  if(typeof fields.taskId!=="string"||typeof fields.reason!=="string"||
     fields.reason.trim().length<10||fields.reason.trim().length>500)
    return ownerResponse({error:"Explicit completion reason required"},422);
  try{return ownerResponse(await completeInternalAutomationTask(
    actor,(await params).id,fields.taskId,fields.reason));}
  catch{return ownerResponse({error:"Task is not pending or cannot be completed"},409);}
}
