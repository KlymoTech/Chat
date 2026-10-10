import { NextResponse } from "next/server";
export const dynamic = "force-dynamic";

/** Liveness only. 200 does not imply databases, consent, security or launch readiness. */
export function GET() {
  return NextResponse.json({status:"alive",scope:"process"},{
    headers:{"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"},
  });
}
