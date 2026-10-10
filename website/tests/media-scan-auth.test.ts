import {describe,expect,it} from "vitest";
import {
  readPrivateScanRequest,signPrivateScanRequest,verifyPrivateScanRequest,
} from "../src/lib/media-scan-auth";

const siteId="550e8400-e29b-41d4-a716-446655440000";
const assetId="62a2a2bf-1b2a-4fe2-a333-12b2a2a2a2a2";
const request={siteId,assetId};
const secret="server-only-secret-with-at-least-32-chars";
const at=1700000000000;

describe("private media scan trigger",()=>{
  it("accepts only well formed site and asset identifiers",()=>{
    expect(readPrivateScanRequest(JSON.stringify(request))).toEqual(request);
    expect(readPrivateScanRequest(JSON.stringify({...request,siteId:"../other"}))).toBeNull();
    expect(readPrivateScanRequest(JSON.stringify({...request,assetId:"../../private"}))).toBeNull();
    expect(readPrivateScanRequest('{"siteId":')).toBeNull();
    expect(readPrivateScanRequest("x".repeat(513))).toBeNull();
  });
  it("accepts a valid short-lived HMAC signature",()=>{
    const signed=signPrivateScanRequest(request,secret,at);
    expect(verifyPrivateScanRequest(signed.body,new Headers(signed.headers),secret,at)).toEqual(request);
  });
  it("rejects tampering, changed secrets and mismatched assets",()=>{
    const signed=signPrivateScanRequest(request,secret,at);
    expect(verifyPrivateScanRequest(signed.body.replace(assetId,siteId),
      new Headers(signed.headers),secret,at)).toBeNull();
    expect(verifyPrivateScanRequest(signed.body,new Headers(signed.headers),
      "different-secret-at-least-32-characters",at)).toBeNull();
  });
  it("rejects expired signatures and missing secret",()=>{
    const signed=signPrivateScanRequest(request,secret,at);
    expect(verifyPrivateScanRequest(signed.body,new Headers(signed.headers),
      secret,at+121000)).toBeNull();
    expect(verifyPrivateScanRequest(signed.body,new Headers(signed.headers),
      undefined,at)).toBeNull();
    expect(()=>signPrivateScanRequest(request,"short",at)).toThrow();
  });
});
