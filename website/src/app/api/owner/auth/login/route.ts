import { randomBytes, createHash } from "node:crypto";
import { NextResponse } from "next/server";
import { ownerOidcConfig } from "../../../../../lib/owner-oidc";
import { encryptOwnerCookie, sessionConfigured, secureCookie, stateCookie } from "../../../../../lib/owner-session";

export const dynamic="force-dynamic";
export async function GET() {
  const config=ownerOidcConfig();
  if (!config || !sessionConfigured()) return NextResponse.json(
    {error:"Owner sign-in is not configured"}, {status:503,headers:{"Cache-Control":"no-store"}});
  const state=randomBytes(24).toString("base64url");
  const verifier=randomBytes(32).toString("base64url");
  const nonce=randomBytes(24).toString("base64url");
  const challenge=createHash("sha256").update(verifier).digest("base64url");
  const url=new URL(config.authorizationEndpoint);
  url.searchParams.set("response_type","code");
  url.searchParams.set("scope","openid");
  url.searchParams.set("client_id",config.clientId);
  url.searchParams.set("redirect_uri",config.callback);
  url.searchParams.set("code_challenge",challenge);
  url.searchParams.set("code_challenge_method","S256");
  url.searchParams.set("state",state);
  url.searchParams.set("nonce",nonce);
  const token=await encryptOwnerCookie("oidc-state",{state,verifier,nonce},600);
  const response=NextResponse.redirect(url);
  response.headers.set("Cache-Control","no-store");
  response.cookies.set(stateCookie,token,{...secureCookie,maxAge:600});
  return response;
}
