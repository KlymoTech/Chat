/** OIDC signing keys must be fetched from the configured issuer's HTTPS origin. */
export function trustedOwnerJwksEndpoint(issuer:string|undefined,jwks:string|undefined):boolean{
  if(!issuer||!jwks)return false;
  try{
    const iss=new URL(issuer);
    const keys=new URL(jwks);
    if(iss.protocol!=="https:"||keys.protocol!=="https:"||iss.origin!==keys.origin)
      return false;
    return [iss,keys].every(u=>!u.username&&!u.password&&!u.search&&!u.hash);
  }catch{return false;}
}
