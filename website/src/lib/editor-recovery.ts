/** Session-only, explicitly opted-in CMS recovery. Never publishes data. */
import {validBlockIdentity,validBuilderSection} from "./builder-contract";
import type {PublicBlock} from "./cms";
export const RECOVERY_TTL_MS=2*60*60*1000;
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
type Draft={title:string;description:string;blocks:PublicBlock[]};
export type DraftRecovery=Readonly<{
  version:1;siteId:string;ownerId:string;pageId:string;
  expectedVersion:number;storedAt:number;document:Draft;
}>;
function validDraft(input:unknown):input is Draft{
  if(!input||typeof input!=="object"||Array.isArray(input))return false;
  const value=input as Record<string,unknown>;
  if(typeof value.title!=="string"||value.title.length>180||
     typeof value.description!=="string"||value.description.length>500||
     !Array.isArray(value.blocks)||value.blocks.length>100)return false;
  const ids=new Set<string>();
  return value.blocks.every((raw:unknown)=>{
    if(!raw||typeof raw!=="object"||Array.isArray(raw))return false;
    const b=raw as Record<string,unknown>;
    if(!validBlockIdentity(b))return false;
    if(typeof b.blockId==="string"){
      if(ids.has(b.blockId.toLowerCase()))return false;
      ids.add(b.blockId.toLowerCase());
    }
    if(b.type==="hero"||b.type==="cta"||b.type==="faq")return validBuilderSection(b);
    if(b.type==="heading"||b.type==="paragraph")
      return typeof b.text==="string"&&b.text.length<=5000;
    if(b.type==="callout")return typeof b.title==="string"&&b.title.length<=180
      &&typeof b.body==="string"&&b.body.length<=5000;
    if(b.type==="image")return typeof b.assetId==="string"&&b.assetId.length<=36
      &&typeof b.alt==="string"&&b.alt.length<=300
      &&typeof b.caption==="string"&&b.caption.length<=500;
    return false;
  });
}
export function recoveryStorageKey(siteId:string,ownerId:string,pageId:string):string{
  if(!uuid.test(siteId)||!uuid.test(ownerId)||!uuid.test(pageId))
    throw new Error("Invalid recovery scope");
  return ["website","cms-recovery","v1",siteId.toLowerCase(),
    ownerId.toLowerCase(),pageId.toLowerCase()].join(":");
}
export function createRecovery(record:Omit<DraftRecovery,"version"|"storedAt">,
  now=Date.now()):string|null{
  try{
    recoveryStorageKey(record.siteId,record.ownerId,record.pageId);
    if(!Number.isSafeInteger(record.expectedVersion)||record.expectedVersion<0||
       !validDraft(record.document)||!Number.isFinite(now))return null;
    const encoded=JSON.stringify({...record,version:1,storedAt:now});
    return encoded.length<=100000?encoded:null;
  }catch{return null;}
}
export function parseRecovery(raw:string|null,scope:{
  siteId:string;ownerId:string;pageId:string;
},now=Date.now()):DraftRecovery|null{
  if(!raw||raw.length>100000)return null;
  try{
    recoveryStorageKey(scope.siteId,scope.ownerId,scope.pageId);
    const parsed:unknown=JSON.parse(raw);
    if(!parsed||typeof parsed!=="object"||Array.isArray(parsed))return null;
    const x=parsed as Record<string,unknown>;
    if(x.version!==1||typeof x.storedAt!=="number"||
       !Number.isFinite(x.storedAt)||x.storedAt>now||
       now-x.storedAt>=RECOVERY_TTL_MS||x.siteId!==scope.siteId||
       x.ownerId!==scope.ownerId||x.pageId!==scope.pageId||
       !Number.isSafeInteger(x.expectedVersion)||Number(x.expectedVersion)<0||
       !validDraft(x.document))return null;
    return x as unknown as DraftRecovery;
  }catch{return null;}
}
