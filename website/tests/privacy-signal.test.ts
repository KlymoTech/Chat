import {describe,expect,it} from "vitest";
import {applyBrowserOptOut,hasGlobalPrivacyControl} from "../src/lib/privacy-signal";
describe("global privacy control restrictions",()=>{
  it("accepts only explicit Sec-GPC: 1",()=>{
    expect(hasGlobalPrivacyControl(new Headers({"Sec-GPC":"1"}))).toBe(true);
    expect(hasGlobalPrivacyControl(new Headers({"Sec-GPC":"0"}))).toBe(false);
    expect(hasGlobalPrivacyControl(new Headers())).toBe(false);
  });
  it("never enables optional marketing under active GPC",()=>{
    expect(applyBrowserOptOut({analytics:true,marketing:true},true)).toEqual({
      analytics:true,marketing:false,gpcApplied:true,
    });
    expect(applyBrowserOptOut({analytics:false,marketing:false},true)).toEqual({
      analytics:false,marketing:false,gpcApplied:true,
    });
    expect(applyBrowserOptOut({analytics:true,marketing:true},false)).toEqual({
      analytics:true,marketing:true,gpcApplied:false,
    });
  });
});
