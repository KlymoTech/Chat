import {createHmac,timingSafeEqual} from "node:crypto";

const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export type PrivateScanRequest=Readonly<{siteId:string;assetId:string}>;

export function readPrivateScanRequest(raw:string):PrivateScanRequest|null {
  if(typeof raw!=="string"||raw.length>512)return null;
  try{
    const value:unknown=JSON.parse(raw);
    if(!value||typeof value!=="object"||Array.isArray(value))return null;
    const data=value as Record<string,unknown>;
    if(typeof data.siteId!=="string"||!uuid.test(data.siteId)||
       typeof data.assetId!=="string"||!uuid.test(data.assetId))return null;
    return {siteId:data.siteId,assetId:data.assetId};
  }catch{return null;}
}
export function signPrivateScanRequest(
  data:PrivateScanRequest,secret:string,at=Date.now(),
):{body:string;headers:Record<string,string>} {
  const body=JSON.stringify(data);
  if(!readPrivateScanRequest(body)||typeof secret!=="string"||secret.length<32)
    throw new Error("Private scanner not configured");
  const timestamp=Math.floor(at/1000).toString();
  const signature=createHmac("sha256",secret).update(timestamp+"."+body).digest("hex");
  return {body,headers:{
    "Content-Type":"application/json",
    "X-Media-Scan-Timestamp":timestamp,
    "X-Media-Scan-Signature":"sha256="+signature,
  }};
}
export function verifyPrivateScanRequest(
  raw:string,headers:Headers,secret:string|undefined,now=Date.now(),
):PrivateScanRequest|null {
  if(!secret||secret.length<32)return null;
  const timestamp=headers.get("x-media-scan-timestamp");
  const signature=headers.get("x-media-scan-signature");
  if(!timestamp||!/^[1-9][0-9]{9,11}$/.test(timestamp)||
     !signature||!/^sha256=[0-9a-f]{64}$/.test(signature)||
     Math.abs(now/1000-Number(timestamp))>120)return null;
  const expected=createHmac("sha256",secret).update(timestamp+"."+raw).digest();
  const actual=Buffer.from(signature.slice(7),"hex");
  if(actual.length!==expected.length||!timingSafeEqual(actual,expected))return null;
  return readPrivateScanRequest(raw);
}
