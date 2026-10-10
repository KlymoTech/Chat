import {describe,expect,it} from "vitest";
import {ownerMfaSatisfied} from "../src/lib/owner-mfa-policy";
const now=1800000000;
describe("production OIDC MFA gate",()=>{
  it("preserves legacy behavior only when the MFA gate is explicitly off",()=>{
    expect(ownerMfaSatisfied({}, {required:false},now)).toBe(true);
    expect(ownerMfaSatisfied({}, {required:true},now)).toBe(false);
  });
  it("accepts recent IdP MFA factor in the verified access token",()=>{
    for(const method of ["mfa","otp","hwk","swk","fido","webauthn"]){
      expect(ownerMfaSatisfied({auth_time:now-3600,amr:["pwd",method]},
        {required:true},now)).toBe(true);
    }
  });
  it("denies password-only, stale, future or missing authentication evidence",()=>{
    const config={required:true};
    expect(ownerMfaSatisfied({auth_time:now-100,amr:["pwd"]},config,now)).toBe(false);
    expect(ownerMfaSatisfied({amr:["mfa"]},config,now)).toBe(false);
    expect(ownerMfaSatisfied({auth_time:now-43201,amr:["mfa"]},config,now)).toBe(false);
    expect(ownerMfaSatisfied({auth_time:now+61,amr:["mfa"]},config,now)).toBe(false);
    expect(ownerMfaSatisfied({auth_time:"1800000000",amr:["mfa"]},config,now)).toBe(false);
    expect(ownerMfaSatisfied({auth_time:now-100,amr:["pwd","unknown"]},
      config,now)).toBe(false);
  });
  it("supports only exact operator-approved high-assurance ACR",()=>{
    const acr="urn:company:authentication:multi-factor";
    expect(ownerMfaSatisfied({auth_time:now-60,acr},
      {required:true,acceptedAcr:acr},now)).toBe(true);
    expect(ownerMfaSatisfied({auth_time:now-60,acr:"urn:company:password-only"},
      {required:true,acceptedAcr:acr},now)).toBe(false);
    expect(ownerMfaSatisfied({auth_time:now-60,acr},
      {required:true},now)).toBe(false);
  });
});
