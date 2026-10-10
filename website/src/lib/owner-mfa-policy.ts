/** Fail-closed optional MFA requirement for validated OIDC access-token claims.
 * Enabled only after the organization's IdP claim mapping is accepted. */
const methods = new Set(["mfa","otp","hwk","swk","fido","webauthn"]);
export function ownerMfaSatisfied(
  claims: Record<string,unknown>,
  config: {required:boolean;acceptedAcr?:string;maxAgeSeconds?:number},
  nowSeconds=Math.floor(Date.now()/1000),
):boolean {
  if(!config.required)return true;
  const ageLimit=config.maxAgeSeconds??43200;
  if(!Number.isFinite(nowSeconds)||!Number.isSafeInteger(ageLimit)||
     ageLimit<=0||ageLimit>86400)return false;
  const time=claims.auth_time;
  if(typeof time!=="number"||!Number.isSafeInteger(time)||
     time>nowSeconds+60||nowSeconds-time>ageLimit)return false;
  const amr=claims.amr;
  const strongMethod=Array.isArray(amr)&&amr.length>0&&amr.length<=12&&
    amr.every(x=>typeof x==="string"&&x.length<=50)&&
    amr.some(x=>methods.has(x.toLowerCase()));
  const acr=claims.acr;
  const trustedAcr=typeof config.acceptedAcr==="string"&&
    config.acceptedAcr.length>=8&&config.acceptedAcr.length<=256&&
    typeof acr==="string"&&acr===config.acceptedAcr;
  return strongMethod||trustedAcr;
}
