import { NextRequest, NextResponse } from "next/server";
import { ownerOidcConfig } from "../../../../../lib/owner-oidc";
import { sessionCookie, stateCookie, secureCookie } from "../../../../../lib/owner-session";
export async function POST(request:NextRequest) {
  const config=ownerOidcConfig();
  if (!config || request.headers.get("origin")!==config.origin)
    return NextResponse.json({error:"Origin not allowed"},{status:403,headers:{"Cache-Control":"no-store"}});
  const response=NextResponse.json({signedOut:true},{headers:{"Cache-Control":"no-store"}});
  response.cookies.set(sessionCookie,"",{...secureCookie,maxAge:0});
  response.cookies.set(stateCookie,"",{...secureCookie,maxAge:0});
  return response;
}
