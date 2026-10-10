import {describe,expect,it} from "vitest";
import {
  CMS_EVENTS,cmsRetryDelaySeconds,parseCmsInvalidation,
  signCmsInvalidation,verifyCmsInvalidation,verifiedCmsOrigin,
} from "../scripts/cms-invalidation-contract.mjs";
const event={
  eventId:"550e8400-e29b-41d4-a716-446655440000",
  pageId:"62a2a2bf-1b2a-4fe2-a333-12b2a2a2a2a2",
  eventType:"cms.published",path:"/content/a-good-article",
};
const secret="z".repeat(48);
const when=1700000000000;
describe("durable CMS publication delivery contract",()=>{
  it("allows exactly the four editorial visibility events",()=>{
    expect(CMS_EVENTS).toEqual([
      "cms.published","cms.restored","cms.trashed","cms.restored_from_trash"
    ]);
    for(const eventType of CMS_EVENTS) {
      expect(parseCmsInvalidation({...event,eventType})?.eventType).toBe(eventType);
    }
  });
  it("signs, verifies and binds exact event ID, body and clock",()=>{
    const {body,headers}=signCmsInvalidation(event,secret,when);
    const h=new Headers(headers);
    expect(verifyCmsInvalidation(body,h,secret,when)).toEqual(event);
    expect(verifyCmsInvalidation(body.replace("published","trashed"),h,secret,when)).toBeNull();
    h.set("X-CMS-Event-Id","62a2a2bf-1b2a-4fe2-a333-12b2a2a2a2a2");
    expect(verifyCmsInvalidation(body,h,secret,when)).toBeNull();
  });
  it("rejects expired signatures and tampered or unsupported paths",()=>{
    const {body,headers}=signCmsInvalidation(event,secret,when);
    expect(verifyCmsInvalidation(body,new Headers(headers),secret,when+121000)).toBeNull();
    for(const path of ["/admin","/owner","/api/health","/content/../../private",
      "/content/a/b","/content/%2F","https://evil.example/path"]) {
      expect(parseCmsInvalidation({...event,path})).toBeNull();
    }
    expect(parseCmsInvalidation({...event,eventType:"cms.purged"})).toBeNull();
  });
  it("requires HTTPS site origin, not loopback, credentials or unexpected ports",()=>{
    expect(verifiedCmsOrigin("https://website.business.tld/")).toBe("https://website.business.tld");
    for(const url of ["http://website.business.tld/","https://localhost/",
      "https://127.0.0.1/","https://website.business.tld:8080/",
      "https://user:pw@website.business.tld/","https://website.business.tld/private"]) {
      expect(verifiedCmsOrigin(url)).toBeNull();
    }
  });
  it("bounds retries without discarding an event after repeated failures",()=>{
    expect(cmsRetryDelaySeconds(1)).toBe(30);
    expect(cmsRetryDelaySeconds(2)).toBe(60);
    expect(cmsRetryDelaySeconds(20)).toBe(86400);
    expect(()=>cmsRetryDelaySeconds(0)).toThrow();
  });
});
