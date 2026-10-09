import {loadPublicApprovedMedia} from "../../../lib/media-public-read";

export const dynamic="force-dynamic";
export const revalidate=0;
export const runtime="nodejs";
const deniedHeaders={
  "Cache-Control":"no-store, max-age=0",
  "X-Content-Type-Options":"nosniff",
  "X-Robots-Tag":"noindex",
};
/** Public delivery for explicitly published, reviewed WebP derivatives ONLY. */
export async function GET(
  _request:Request,{params}:{params:Promise<{assetId:string}>},
) {
  if(process.env.WEBSITE_MEDIA_PUBLIC_DELIVERY_ENABLED!=="true"||
     process.env.WEBSITE_MEDIA_PUBLIC_READER_GRANTS_VERIFIED!=="true")
    return new Response(null,{status:503,headers:deniedHeaders});
  const {assetId}=await params;
  const bytes=await loadPublicApprovedMedia(assetId);
  if(!bytes)return new Response(null,{status:404,headers:deniedHeaders});
  return new Response(new Uint8Array(bytes),{status:200,headers:{
    ...deniedHeaders,
    "Content-Type":"image/webp",
    "Content-Length":String(bytes.byteLength),
    "Content-Disposition":'inline; filename="published-asset.webp"',
    "Cross-Origin-Resource-Policy":"same-origin",
  }});
}
