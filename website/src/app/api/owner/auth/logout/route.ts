import { NextRequest, NextResponse } from "next/server";
import { sessionCookie, stateCookie, secureCookie } from "../../../../../lib/owner-session";
/** Local sign-out works even when the owner feature is subsequently disabled. */
export async function POST(request:NextRequest) {
  const expected=process.env.WEBSITE_CANONICAL_ORIGIN;
  if (!expected || request.headers.get("origin")!==expected)
    return NextResponse.json({error:"Origin not allowed"},{status:403,headers:{"Cache-Control":"no-store"}});
  const response=NextResponse.json({signedOut:true},{headers:{"Cache-Control":"no-store"}});
  response.cookies.set(sessionCookie,"",{...secureCookie,maxAge:0});
  response.cookies.set(stateCookie,"",{...secureCookie,maxAge:0});
  return response;
}
