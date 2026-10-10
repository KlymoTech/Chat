/** Retired content URLs can redirect to approved, canonical internal routes only. */
export const REDIRECT_SOURCE=/^\/content\/[a-z0-9]+(?:-[a-z0-9]+)*$/;
export const REDIRECT_DESTINATION=/^\/(?:services|about|contact|resources|blog|privacy|terms|content\/[a-z0-9]+(?:-[a-z0-9]+)*)$/;
export type RedirectDraft={sourcePath:string;targetPath:string;reasonCode:"slug_change"|"consolidated_content"|"replaced_content"};
export function parseRedirectDraft(value:unknown):RedirectDraft|null{
  if(!value||typeof value!=="object"||Array.isArray(value))return null;
  const x=value as Record<string,unknown>;
  if(Object.keys(x).some(k=>!["sourcePath","targetPath","reasonCode"].includes(k))||
     typeof x.sourcePath!=="string"||!REDIRECT_SOURCE.test(x.sourcePath)||
     typeof x.targetPath!=="string"||!REDIRECT_DESTINATION.test(x.targetPath)||
     x.sourcePath===x.targetPath||
     !["slug_change","consolidated_content","replaced_content"].includes(String(x.reasonCode)))
    return null;
  return {sourcePath:x.sourcePath,targetPath:x.targetPath,
    reasonCode:x.reasonCode as RedirectDraft["reasonCode"]};
}
/** Routes with private content, encoded delimiters, fragments or queries are denied. */
export function isRedirectLookupSource(value:unknown):value is string{
  return typeof value==="string"&&value.length<=512&&REDIRECT_SOURCE.test(value);
}
