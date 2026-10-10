import {NextResponse} from "next/server";
import {requireOwner,ownerResponse} from "../../../../../../../lib/owner-api";
import {readRightsCaseHistory} from "../../../../../../../lib/privacy-rights-service";
export const dynamic="force-dynamic";
export async function GET(request:Request,{params}:{
  params:Promise<{id:string}>
}){
  const actor=await requireOwner(request,"cms:privacy");
  if(actor instanceof NextResponse)return actor;
  try{
    const history=await readRightsCaseHistory(actor,(await params).id);
    return history?ownerResponse({history}):ownerResponse({error:"Case not found"},404);
  }catch{return ownerResponse({error:"Private case history unavailable"},503);}
}
