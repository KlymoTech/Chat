/** Version 1.3 safe visual-builder contract: legacy blocks remain valid. */
export const BUILDER_SCHEMA_VERSION=1 as const;
export const BLOCK_ID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export const ACTION_PATH=/^(?:\/(?:contact|services|resources|blog|about)|\/content\/[a-z0-9]+(?:-[a-z0-9]+)*)$/;

export type BuilderIdentity={blockId?:string;schemaVersion?:1};
export type HeroBlock=BuilderIdentity & {
  type:"hero";eyebrow:string;heading:string;description:string;
  actionLabel:string;actionPath:string;variant:"center"|"split";
};
export type CtaBlock=BuilderIdentity & {
  type:"cta";heading:string;description:string;actionLabel:string;
  actionPath:string;variant:"solid"|"outline";
};
export type FaqBlock=BuilderIdentity & {
  type:"faq";items:{question:string;answer:string}[];
};
export type BuilderSection=HeroBlock|CtaBlock|FaqBlock;
type Value=Record<string,unknown>;
const text=(v:unknown,max:number,required=false)=>
  typeof v==="string" && v.length<=max && (!required||v.trim().length>0);
export function validBlockIdentity(v:Value):boolean {
  return (v.blockId===undefined||typeof v.blockId==="string"&&BLOCK_ID.test(v.blockId)) &&
    (v.schemaVersion===undefined||v.schemaVersion===1);
}
export function validBuilderSection(block:unknown):block is BuilderSection {
  if(!block||typeof block!=="object"||Array.isArray(block))return false;
  const b=block as Value;
  if(!validBlockIdentity(b))return false;
  if(b.type==="hero"||b.type==="cta") {
    if(!text(b.heading,180,true)||!text(b.description,1200)||
       !text(b.actionLabel,80,true)||typeof b.actionPath!=="string"||
       !ACTION_PATH.test(b.actionPath))return false;
    if(b.type==="hero")return text(b.eyebrow,100) &&
      (b.variant==="center"||b.variant==="split");
    return b.variant==="solid"||b.variant==="outline";
  }
  if(b.type==="faq"){
    return Array.isArray(b.items)&&b.items.length>=1&&b.items.length<=20 &&
      b.items.every((item:unknown)=>!!item&&typeof item==="object"&&!Array.isArray(item)&&
        text((item as Value).question,240,true)&&text((item as Value).answer,2000,true));
  }
  return false;
}
export function freshBuilderBlock(type:"hero",id:string):HeroBlock;
export function freshBuilderBlock(type:"cta",id:string):CtaBlock;
export function freshBuilderBlock(type:"faq",id:string):FaqBlock;
export function freshBuilderBlock(type:"hero"|"cta"|"faq",id:string):BuilderSection;
export function freshBuilderBlock(type:"hero"|"cta"|"faq",id:string):BuilderSection {
  if(!BLOCK_ID.test(id))throw new Error("Stable block ID must be a UUID");
  const identity={blockId:id,schemaVersion:1 as const};
  switch(type){
    case "hero":return {...identity,type,eyebrow:"",heading:"New hero heading",
      description:"",actionLabel:"Contact us",actionPath:"/contact",variant:"center"};
    case "cta":return {...identity,type,heading:"Let's talk",description:"",
      actionLabel:"Contact us",actionPath:"/contact",variant:"solid"};
    case "faq":return {...identity,type,items:[{question:"New question",answer:"Add an approved answer"}]};
  }
}
/** Validate stable IDs without rewriting old immutable published snapshots. */
export function validBuilderIdentities(blocks:readonly unknown[]):boolean {
  const ids=new Set<string>();
  for(const block of blocks){
    if(!block||typeof block!=="object"||Array.isArray(block))return false;
    const o=block as Value;
    if(!validBlockIdentity(o))return false;
    if(typeof o.blockId==="string"){
      if(ids.has(o.blockId.toLowerCase()))return false;
      ids.add(o.blockId.toLowerCase());
    }
  }
  return true;
}
