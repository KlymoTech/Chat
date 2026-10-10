import { timingSafeEqual } from "node:crypto";
import { createRemoteJWKSet, jwtVerify } from "jose";
import { NextRequest, NextResponse } from "next/server";
import { ownerOidcConfig } from "../../../../../lib/owner-oidc";
import { readOwnerCookie, encryptOwnerCookie, secureCookie, stateCookie, sessionCookie } from "../../../../../lib/owner-session";
import { authenticateOwner } from "../../../../../lib/owner-auth";

export const dynamic="force-dynamic";
const noStore={"Cache-Control":"no-store"};
function same(a:string,b:string):boolean {
  const left=Buffer.from(a),right=Buffer.from(b);
  return left.length===right.length && timingSafeEqual(left,right);
}
export async function GET(request:NextRequest) {
  const config=ownerOidcConfig();
  const state=await readOwnerCookie(request,stateCookie,"oidc-state");
  const result=NextResponse.redirect(new URL("/owner?login=failed",config?.origin||request.nextUrl.origin));
  result.headers.set("Cache-Control","no-store");
  result.cookies.set(stateCookie,"",{...secureCookie,maxAge:0});
  if (!config || !state || typeof state.state!=="string" ||
      typeof state.verifier!=="string" || typeof state.nonce!=="string") return result;
  const code=request.nextUrl.searchParams.get("code");
  const returnedState=request.nextUrl.searchParams.get("state");
  if (!code || code.length>4096 || !returnedState || !same(returnedState,state.state)) return result;
  try {
    const response=await fetch(config.tokenEndpoint,{
      method:"POST",redirect:"error",cache:"no-store",
      headers:{"Content-Type":"application/x-www-form-urlencoded","Accept":"application/json"},
      body:new URLSearchParams({
        grant_type:"authorization_code",client_id:config.clientId,code,
        code_verifier:state.verifier,redirect_uri:config.callback
      }),
      signal:AbortSignal.timeout(5000)
    });
    if (!response.ok) return result;
    const body:unknown=await response.json();
    if (!body || typeof body!=="object") return result;
    const fields=body as Record<string,unknown>;
    const access=fields.access_token, idToken=fields.id_token;
    if (typeof access!=="string" || access.length>3000 ||
        typeof idToken!=="string" || idToken.length>8192 || fields.token_type!=="Bearer") return result;
    const jwksUrl=process.env.WEBSITE_CMS_OIDC_JWKS_URL;
    if(!jwksUrl) return result;
    const keyUrl=new URL(jwksUrl);
    if (keyUrl.protocol!=="https:" || keyUrl.origin!==new URL(config.issuer).origin ||
        keyUrl.username || keyUrl.password || keyUrl.search || keyUrl.hash) return result;
    // Validate ID-token signature and binding to this login request (nonce).
    const {payload}=await jwtVerify(idToken,createRemoteJWKSet(keyUrl,{timeoutDuration:3000}),{
      issuer:config.issuer,audience:config.clientId,algorithms:["RS256"],maxTokenAge:"10m",
      clockTolerance:"5s"
    });
    if (payload.nonce!==state.nonce) return result;
    // Independently validate access-token signature, role, tenant and audience.
    const verified=await authenticateOwner(new Request(config.origin,{
      headers:{authorization:"Bearer "+access}
    }));
    if (!verified) return result;
    const sealed=await encryptOwnerCookie("owner-session",{accessToken:access},900);
    if (sealed.length>3800) return result;
    const success=NextResponse.redirect(new URL("/owner",config.origin));
    success.headers.set("Cache-Control","no-store");
    success.cookies.set(stateCookie,"",{...secureCookie,maxAge:0});
    success.cookies.set(sessionCookie,sealed,{...secureCookie,maxAge:900});
    return success;
  } catch { return result; }
}
