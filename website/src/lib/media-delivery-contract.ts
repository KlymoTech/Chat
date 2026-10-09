const assetUuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const digest=/^[0-9a-f]{64}$/;
export type PublicMediaReference=Readonly<{
  id:string; storageKey:string; sha256:string; byteSize:number;
}>;
/** Accept only the already-reviewed sanitized candidate for a UUID-matched asset. */
export function validatePublicMediaReference(value:unknown,requestedId:string):PublicMediaReference|null {
  if(!assetUuid.test(requestedId)||!value||typeof value!=="object"||Array.isArray(value))return null;
  const row=value as Record<string,unknown>;
  if(typeof row.id!=="string"||row.id.toLowerCase()!==requestedId.toLowerCase()||
     typeof row.storage_key!=="string"||typeof row.sha256!=="string"||
     !digest.test(row.sha256))return null;
  const byteSize=typeof row.byte_size==="number"?row.byte_size:
    typeof row.byte_size==="string"&&/^[1-9][0-9]*$/.test(row.byte_size)?
      Number(row.byte_size):NaN;
  if(!Number.isSafeInteger(byteSize)||byteSize<12||byteSize>10*1024*1024)return null;
  const match=/^processed[/]([0-9a-f-]{36})[/]([0-9a-f-]{36})[/]candidate[.]webp$/.exec(row.storage_key);
  if(!match||!assetUuid.test(match[1])||match[2].toLowerCase()!==requestedId.toLowerCase())
    return null;
  return {id:row.id,storageKey:row.storage_key,sha256:row.sha256,byteSize};
}
/** Operator-configured HTTPS DNS endpoint, no arbitrary or user-selected URLs. */
export function approvedPublicStoreEndpoint(value:unknown):string|null {
  if(typeof value!=="string")return null;
  try{
    const url=new URL(value);
    const host=url.hostname.toLowerCase();
    if(url.protocol!=="https:"||url.username||url.password||url.search||url.hash||
       url.pathname!=="/"||url.port||!host.includes(".")||
       !/^[a-z0-9.-]+$/.test(host)||/^[0-9]+(?:[.][0-9]+){3}$/.test(host)||
       host.endsWith(".local")||host.endsWith(".localhost")||
       host.endsWith(".internal")||host.endsWith(".test")||host.endsWith(".example"))
      return null;
    return url.origin;
  }catch{return null;}
}
