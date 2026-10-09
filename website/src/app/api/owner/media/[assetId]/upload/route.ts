import {NextResponse} from "next/server";
import {uploadQuarantinedMedia,MediaUploadConflict,MediaUploadRejected} from "../../../../../../lib/media-editor";
import {ownerResponse,requireOwner} from "../../../../../../lib/owner-api";

export const dynamic="force-dynamic";
export const runtime="nodejs";
type Params={params:Promise<{assetId:string}>};
const maxBytes=10*1024*1024;

/** Accept raw binary bytes only. Never provide public download URLs or approval. */
export async function PUT(request:Request,{params}:Params){
  const actor=await requireOwner(request,"cms:media");
  if(actor instanceof NextResponse)return actor;
  if(process.env.WEBSITE_MEDIA_UPLOAD_ENABLED!=="true"||
     process.env.WEBSITE_MEDIA_MANIFEST_ENABLED!=="true")
    return ownerResponse({error:"Quarantine uploads disabled"},503);
  if(request.headers.get("origin")!==process.env.WEBSITE_CANONICAL_ORIGIN)
    return ownerResponse({error:"Origin not allowed"},403);
  if(request.headers.get("content-type")!=="application/octet-stream")
    return ownerResponse({error:"Binary body required"},415);
  const rawLength=request.headers.get("content-length");
  const size=rawLength===null?NaN:Number(rawLength);
  if(!Number.isSafeInteger(size) || size<12 || size>maxBytes)
    return ownerResponse({error:"Valid Content-Length required (max 10 MB)"},413);
  const {assetId}=await params;
  let bytes:Uint8Array;
  try{
    const blob=await request.arrayBuffer();
    if(blob.byteLength!==size || blob.byteLength>maxBytes)
      return ownerResponse({error:"Upload length mismatch"},422);
    bytes=new Uint8Array(blob);
  }catch{
    return ownerResponse({error:"Unable to read upload"},422);
  }
  try{
    const result=await uploadQuarantinedMedia(actor,assetId,bytes);
    return ownerResponse({...result,scanStatus:"pending",publicAccess:false},200);
  }catch(error){
    if(error instanceof MediaUploadRejected)
      return ownerResponse({error:"Invalid image bytes or media record"},422);
    if(error instanceof MediaUploadConflict)
      return ownerResponse({error:"Media record is not accepting uploads"},409);
    return ownerResponse({error:"Private quarantine storage unavailable"},503);
  }
}
