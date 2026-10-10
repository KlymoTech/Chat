import { afterEach, describe, expect, it, vi } from "vitest";
vi.mock("server-only",()=>({}));
import { ownerOidcConfig } from "../src/lib/owner-oidc";
import { encryptOwnerCookie, readOwnerCookie, sessionCookie } from "../src/lib/owner-session";

afterEach(()=>vi.unstubAllEnvs());
function approvedConfig(){
  vi.stubEnv("WEBSITE_CMS_OWNER_API_ENABLED","true");
  vi.stubEnv("WEBSITE_CMS_OWNER_DB_RLS_VERIFIED","true");
  vi.stubEnv("WEBSITE_CANONICAL_ORIGIN","https://site.example/");
  vi.stubEnv("WEBSITE_CMS_OIDC_ISSUER","https://auth.example/tenant");
  vi.stubEnv("WEBSITE_CMS_OIDC_AUDIENCE","website-owner-api");
  vi.stubEnv("WEBSITE_CMS_OIDC_CLIENT_ID","website-owner-web");
  vi.stubEnv("WEBSITE_CMS_OIDC_AUTHORIZATION_ENDPOINT","https://auth.example/oauth2/authorize");
  vi.stubEnv("WEBSITE_CMS_OIDC_TOKEN_ENDPOINT","https://auth.example/oauth2/token");
}
describe("owner OIDC configuration safety",()=>{
  it("stays disabled without operator approval",()=>{
    vi.stubEnv("WEBSITE_CMS_OWNER_API_ENABLED","false");
    expect(ownerOidcConfig()).toBeNull();
  });
  it("constructs exact HTTPS callback for configured issuer endpoints",()=>{
    approvedConfig();
    expect(ownerOidcConfig()?.callback).toBe("https://site.example/api/owner/auth/callback");
  });
  it("rejects insecure and cross-origin provider endpoints",()=>{
    approvedConfig();
    vi.stubEnv("WEBSITE_CMS_OIDC_TOKEN_ENDPOINT","https://unrelated.example/oauth/token");
    expect(ownerOidcConfig()).toBeNull();
    vi.stubEnv("WEBSITE_CMS_OIDC_TOKEN_ENDPOINT","http://auth.example/oauth/token");
    expect(ownerOidcConfig()).toBeNull();
    vi.stubEnv("WEBSITE_CMS_OIDC_TOKEN_ENDPOINT","https://auth.example/oauth/token");
    vi.stubEnv("WEBSITE_CANONICAL_ORIGIN","http://localhost:3000");
    expect(ownerOidcConfig()).toBeNull();
  });
});
describe("encrypted HttpOnly session payload",()=>{
  it("decrypts only a matching purpose and cookie",async()=>{
    vi.stubEnv("WEBSITE_CMS_SESSION_KEY","A".repeat(43));
    const cookie=await encryptOwnerCookie("owner-session",{accessToken:"sample"},300);
    const request=new Request("https://site.example/owner",{
      headers:{"cookie":sessionCookie+"="+cookie}
    });
    expect((await readOwnerCookie(request,sessionCookie,"owner-session"))?.accessToken).toBe("sample");
    expect(await readOwnerCookie(request,sessionCookie,"oidc-state")).toBeNull();
  });
  it("denies tampered payloads",async()=>{
    vi.stubEnv("WEBSITE_CMS_SESSION_KEY","A".repeat(43));
    const cookie=await encryptOwnerCookie("owner-session",{accessToken:"sample"},300);
    const wrong=cookie.slice(0,-3)+"xyz";
    const request=new Request("https://site.example/owner",{
      headers:{"cookie":sessionCookie+"="+wrong}
    });
    expect(await readOwnerCookie(request,sessionCookie,"owner-session")).toBeNull();
  });
});
