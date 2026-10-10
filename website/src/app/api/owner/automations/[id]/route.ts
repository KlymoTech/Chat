import {NextResponse} from "next/server";
import {bodyJson,checkMutationRequest,ownerResponse,requireOwner} from "../../../../../lib/owner-api";
import {getAutomationDefinition,saveAutomationRevision} from "../../../../../lib/automation-drafts";
import {validateAutomation} from "../../../../../lib/automation-contract";
export const dynamic="force-dynamic";
type Params={params:Promise<{id:string}>};
export async function GET(request:Request,{params}:Params) {
  const actor=await requireOwner(request,"cms:automation");
  if(actor instanceof NextResponse)return actor;
  try{
    const result=await getAutomationDefinition(actor,(await params).id);
    return result?ownerResponse(result):ownerResponse({error:"Not found"},404);
  }catch{return ownerResponse({error:"Unable to load workflow"},503);}
}
export async function POST(request:Request,{params}:Params) {
  const actor=await requireOwner(request,"cms:automation");
  if(actor instanceof NextResponse)return actor;
  const invalid=checkMutationRequest(request);
  if(invalid)return invalid;
  let body:unknown;
  try{body=await bodyJson(request);}catch{return ownerResponse({error:"Invalid request"},422);}
  if(!body||typeof body!=="object"||Array.isArray(body))return ownerResponse({error:"Invalid request"},422);
  const data=body as Record<string,unknown>;
  const graph=validateAutomation(data.definition);
  if(!graph||!Number.isSafeInteger(data.expectedVersion)||Number(data.expectedVersion)<1)
    return ownerResponse({error:"Invalid draft or expected version"},422);
  try{
    return ownerResponse(await saveAutomationRevision(actor,(await params).id,
      data.expectedVersion as number,graph));
  }catch{return ownerResponse({error:"Draft version conflict or storage unavailable. Reload before retry."},409);}
}
