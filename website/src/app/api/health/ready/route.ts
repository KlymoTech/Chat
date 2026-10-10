import { NextResponse } from "next/server";
import { checkPublicCmsReadiness } from "../../../../lib/public-readiness";

export const dynamic = "force-dynamic";
/** Public CMS reader readiness; not a production release certification. */
export async function GET() {
  const result = await checkPublicCmsReadiness();
  return NextResponse.json({
    status: result,
    scope: "public-cms-read",
  },{
    status: result === "ready" ? 200 : 503,
    headers:{"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"},
  });
}
