import {createHmac,timingSafeEqual} from "node:crypto";

export const CMS_EVENTS = Object.freeze([
  "cms.published","cms.restored","cms.trashed","cms.restored_from_trash",
]);
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const pathRule=/^\/content\/[a-z0-9]+(?:-[a-z0-9]+)*$/;

export function parseCmsInvalidation(value) {
  if(!value || typeof value!=="object" || Array.isArray(value))return null;
  const {eventId,pageId,eventType,path}=value;
  if(typeof eventId!=="string" || !uuid.test(eventId) ||
     typeof pageId!=="string" || !uuid.test(pageId) ||
     !CMS_EVENTS.includes(eventType) || typeof path!=="string" ||
     path.length>512 || !pathRule.test(path))return null;
  return {eventId,pageId,eventType,path};
}
export function signCmsInvalidation(message,secret,at=Date.now()) {
  const event=parseCmsInvalidation(message);
  if(!event || typeof secret!=="string" || secret.length<32 ||
     !Number.isFinite(at))throw new Error("CMS invalidation is not configured");
  const timestamp=Math.floor(at/1000).toString();
  const body=JSON.stringify(event);
  const signature=createHmac("sha256",secret).update(timestamp+"."+body).digest("hex");
  return {body,headers:{
    "Content-Type":"application/json",
    "X-CMS-Event-Id":event.eventId,
    "X-CMS-Timestamp":timestamp,
    "X-CMS-Signature":"sha256="+signature,
  }};
}
export function verifyCmsInvalidation(raw,headers,secret,now=Date.now()) {
  if(typeof raw!=="string" || raw.length>4096 || !headers ||
     typeof secret!=="string" || secret.length<32)return null;
  const timestamp=headers.get("x-cms-timestamp");
  const signature=headers.get("x-cms-signature");
  if(!timestamp || !/^[1-9][0-9]{9,11}$/.test(timestamp) ||
     !signature || !/^sha256=[0-9a-f]{64}$/.test(signature))return null;
  const age=Math.abs(now/1000-Number(timestamp));
  if(!Number.isFinite(age)||age>120)return null;
  const expected=createHmac("sha256",secret).update(timestamp+"."+raw).digest();
  const actual=Buffer.from(signature.slice(7),"hex");
  if(actual.length!==expected.length || !timingSafeEqual(actual,expected))return null;
  let decoded;
  try{decoded=JSON.parse(raw);}catch{return null;}
  const event=parseCmsInvalidation(decoded);
  return event && headers.get("x-cms-event-id")===event.eventId ? event : null;
}
export function verifiedCmsOrigin(raw) {
  if(typeof raw!=="string")return null;
  try {
    const url=new URL(raw);
    const host=url.hostname.toLowerCase();
    if(url.protocol!=="https:" || url.username || url.password ||
       url.search || url.hash || url.port || url.pathname!=="/" ||
       !host.includes(".") || host==="localhost" ||
       host.endsWith(".local") || host.endsWith(".internal") ||
       /^[0-9.]+$/.test(host) || host.startsWith("["))return null;
    return url.origin;
  }catch{return null;}
}
export function cmsRetryDelaySeconds(attempt) {
  if(!Number.isSafeInteger(attempt)||attempt<1)throw new Error("Invalid retry count");
  return Math.min(86400,Math.pow(2,Math.min(attempt-1,12))*30);
}
