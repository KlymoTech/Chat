import {NextResponse} from "next/server";
import {classifyBlogDraft,getOwnerBlogClassification} from "../../../../../../lib/blog-editor";
import {bodyJson,checkMutationRequest,ownerResponse,requireOwner} from "../../../../../../lib/owner-api";
import {parseBlogClassification} from "../../../../../../lib/blog-contract";

export const dynamic="force-dynamic";
type Params={params:Promise<{pageId:string}>};
export async function GET(request:Request,{params}:Params){
  const actor=await requireOwner(request,"cms:read");
  if(actor instanceof NextResponse)return actor;
  const {pageId}=await params;
  try{return ownerResponse({blog:await getOwnerBlogClassification(actor,pageId)});}
  catch{return ownerResponse({error:"Blog metadata not available"},404);}
}
export async function POST(request:Request,{params}:Params){
  const actor=await requireOwner(request,"cms:draft");
  if(actor instanceof NextResponse)return actor;
  const invalid=checkMutationRequest(request);
  if(invalid)return invalid;
  let metadata;
  try{metadata=parseBlogClassification(await bodyJson(request));}
  catch{return ownerResponse({error:"Invalid blog metadata"},422);}
  if(!metadata)return ownerResponse({error:"Category and tags required"},422);
  const {pageId}=await params;
  try{return ownerResponse({blog:await classifyBlogDraft(actor,pageId,metadata)});}
  catch{return ownerResponse({error:"Blog classification unavailable or page already published"},409);}
}
