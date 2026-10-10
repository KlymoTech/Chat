import {NextResponse} from "next/server";
import {requireOwner,ownerResponse} from "../../../../../../lib/owner-api";
import {listInternalAutomationRuns} from "../../../../../../lib/internal-automation-runs";
export const dynamic="force-dynamic";
export async function GET(request:Request,{params}:{
 params:Promise<{id:string}>
}){
 const actor=await requireOwner(request,"cms:automation");
 if(actor instanceof NextResponse)return actor;
 try{return ownerResponse({runs:await listInternalAutomationRuns(actor,(await params).id),
   externalDispatch:false});}
 catch{return ownerResponse({error:"Synthetic run history unavailable"},503);}
}
