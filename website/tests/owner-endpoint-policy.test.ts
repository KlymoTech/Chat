import {describe,expect,it} from "vitest";
import {trustedOwnerJwksEndpoint} from "../src/lib/owner-endpoint-policy";
describe("owner OIDC signing-key origin restriction",()=>{
  it("allows only HTTPS keys issued by the same identity-provider origin",()=>{
    expect(trustedOwnerJwksEndpoint(
      "https://login.example.com/tenant-a",
      "https://login.example.com/tenant-a/.well-known/jwks.json")).toBe(true);
  });
  it("refuses a signing key hosted on an attacker-controlled domain",()=>{
    expect(trustedOwnerJwksEndpoint(
      "https://login.example.com/tenant-a",
      "https://another.example.com/tenant-a/jwks.json")).toBe(false);
  });
  it("refuses HTTP, URL credentials, query, fragments and malformed endpoints",()=>{
    const issuer="https://login.example.com/tenant-a";
    for(const url of [
      "http://login.example.com/jwks.json",
      "https://username:password@login.example.com/jwks.json",
      "https://login.example.com/jwks.json?redirect=https://evil.example",
      "https://login.example.com/jwks.json#fragment",
      "not-a-valid-url",
    ])expect(trustedOwnerJwksEndpoint(issuer,url)).toBe(false);
    expect(trustedOwnerJwksEndpoint("http://login.example.com",issuer))
      .toBe(false);
    expect(trustedOwnerJwksEndpoint(undefined,undefined)).toBe(false);
  });
});
