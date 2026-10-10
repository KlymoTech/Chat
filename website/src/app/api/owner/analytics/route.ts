import {NextResponse} from "next/server";
import {requireOwner,ownerResponse} from "../../../../lib/owner-api";
import {getAnalyticsSummary} from "../../../../lib/analytics-report";
export const dynamic="force-dynamic";
export async function GET(request:Request){
  const actor=await requireOwner(request,"cms:read");
  if(actor instanceof NextResponse)return actor;
  try{return ownerResponse({windowDays:30,minimumCohort:5,
    daily:await getAnalyticsSummary(actor),scope:"anonymous first-party events"});}
  catch{return ownerResponse({error:"Aggregate analytics unavailable"},503);}
}
