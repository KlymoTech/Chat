import { describe, expect, it } from "vitest";
import { actorFromVerifiedClaims } from "../src/lib/owner-claims";

const site = "550e8400-e29b-41d4-a716-446655440000";
const user = "62a2a2bf-1b2a-4fe2-a333-12b2a2a2a2a2";
const claims = { sub:user, site_id:site, permissions:["cms:read", "cms:draft"] };
describe("signed owner identity claims", () => {
  it("accepts only a matching site and an allowed permission subset", () => {
    expect(actorFromVerifiedClaims(claims, site)).toEqual({
      id:user, siteId:site, permissions:["cms:read", "cms:draft"]
    });
  });
  it("only accepts redirect permission from a verified matching-site claim",()=>{
    expect(actorFromVerifiedClaims({...claims,permissions:["cms:redirect"]},site))
      .toEqual({id:user,siteId:site,permissions:["cms:redirect"]});
    expect(actorFromVerifiedClaims({...claims,site_id:
      "2d495e1d-bc02-4ddb-a972-d60e2b6c3de5",permissions:["cms:redirect"]},site))
      .toBeNull();
  });
  it("denies tenant switching, missing provisioning and unknown permissions", () => {
    expect(actorFromVerifiedClaims(claims,undefined)).toBeNull();
    expect(actorFromVerifiedClaims(claims,"2d495e1d-bc02-4ddb-a972-d60e2b6c3de5")).toBeNull();
    expect(actorFromVerifiedClaims({...claims,permissions:["cms:publish", "system:admin"]},site)).toBeNull();
  });
  it("denies forged subjects and unexpected claims shapes", () => {
    expect(actorFromVerifiedClaims({...claims,sub:"visitor"},site)).toBeNull();
    expect(actorFromVerifiedClaims({...claims,permissions:"cms:publish"},site)).toBeNull();
    expect(actorFromVerifiedClaims({...claims,site_id:"wrong"},site)).toBeNull();
  });
});
