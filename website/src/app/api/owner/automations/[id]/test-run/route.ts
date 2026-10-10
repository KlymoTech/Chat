import {NextResponse} from "next/server";
import {requireOwner,ownerResponse,checkMutationRequest,bodyJson}
  from "../../../../../../lib/owner-api";
import {enrollSyntheticAutomation}
  from "../../../../../../lib/internal-automation-runs";
export const dynamic="force-dynamic";
export async function POST(request:Request,{params}:{
 params:Promise<{id:string}>
}){
 const actor=await requireOwner(request,"cms:automation");
 if(actor instanceof NextResponse)return actor;
 const invalid=checkMutationRequest(request);
 if(invalid)return invalid;
 let fixture:unknown;
 try{fixture=await bodyJson(request);}
 catch{return ownerResponse({error:"Invalid test fixture"},422);}
 if(!fixture||typeof fixture!=="object"||Array.isArray(fixture))
   return ownerResponse({error:"Invalid test fixture"},422);
 const data=fixture as Record<string,unknown>;
 if((data.sourceCategory!=="form"&&data.sourceCategory!=="subscription")||
    typeof data.marketingConsent!=="boolean"||Object.keys(data).length!==2)
   return ownerResponse({error:"Synthetic context only"},422);
 try{
   return ownerResponse(await enrollSyntheticAutomation(actor,(await params).id,{
     sourceCategory:data.sourceCategory,marketingConsent:data.marketingConsent}),201);
 }catch{return ownerResponse({error:"Synthetic workflow enrollment disabled or unavailable"},503);}
}
