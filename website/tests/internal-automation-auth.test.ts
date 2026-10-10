import {describe,expect,it} from "vitest";
import {signInternalTick,verifyInternalTick}
  from "../src/lib/internal-automation-auth";
const secret="private-operator-secret-with-at-least-32-characters";
const at=1_800_000_000_000;
describe("internal-only automation worker authorization",()=>{
  it("accepts fixed command with 2-minute HMAC boundary",()=>{
    const signed=signInternalTick(secret,at);
    expect(verifyInternalTick(signed.body,new Headers(signed.headers),secret,at))
      .toBe(true);
    expect(verifyInternalTick(signed.body,new Headers(signed.headers),secret,at+119000))
      .toBe(true);
    expect(verifyInternalTick(signed.body,new Headers(signed.headers),secret,at+121000))
      .toBe(false);
  });
  it("rejects changed body, leaked headers and an invalid signing secret",()=>{
    const signed=signInternalTick(secret,at);
    expect(verifyInternalTick('{"operation":"send-to-crm"}',
      new Headers(signed.headers),secret,at)).toBe(false);
    expect(verifyInternalTick(signed.body,new Headers(signed.headers),
      "different-secret-of-sufficient-size-for-tests",at)).toBe(false);
    expect(verifyInternalTick(signed.body,new Headers(signed.headers),undefined,at))
      .toBe(false);
    expect(()=>signInternalTick("weak",at)).toThrow();
  });
});
