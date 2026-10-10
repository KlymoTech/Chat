import {NextResponse} from "next/server";
import {listOwnerMedia,reserveMediaManifest} from "../../../../lib/media-editor";
import {parseMediaManifest} from "../../../../lib/media-contract";
import {readQuarantineStoreConfig} from "../../../../lib/media-storage";
import {bodyJson,checkMutationRequest,ownerResponse,requireOwner} from "../../../../lib/owner-api";

export const dynamic="force-dynamic";

/** Private metadata only. Never exposes quarantine keys or image bytes. */
export async function GET(request:Request) {
  const actor=await requireOwner(request,"cms:media");
  if(actor instanceof NextResponse)return actor;
  if(process.env.WEBSITE_MEDIA_MANIFEST_ENABLED!=="true")
    return ownerResponse({error:"Media intake disabled"},503);
  try{return ownerResponse({media:await listOwnerMedia(actor),
      uploadEnabled:readQuarantineStoreConfig(process.env)!==null});}
  catch{return ownerResponse({error:"Media records unavailable"},503);}
}
/**
 * Reserves manifest ONLY. Does not accept uploaded bytes or treat self-reported
 * MIME/checksum/provenance as scanning or legal-rights verification.
 */
export async function POST(request:Request) {
  const actor=await requireOwner(request,"cms:media");
  if(actor instanceof NextResponse)return actor;
  const invalid=checkMutationRequest(request);
  if(invalid)return invalid;
  if(process.env.WEBSITE_MEDIA_MANIFEST_ENABLED!=="true")
    return ownerResponse({error:"Media intake disabled"},503);
  let value:unknown;
  try{value=await bodyJson(request);}
  catch{return ownerResponse({error:"Invalid JSON manifest"},422);}
  const input=parseMediaManifest(value);
  if(!input)return ownerResponse({error:"Invalid or prohibited media metadata"},422);
  try{
    return ownerResponse(await reserveMediaManifest(actor,input),201);
  }catch{
    return ownerResponse({error:"Unable to reserve media manifest"},503);
  }
}
