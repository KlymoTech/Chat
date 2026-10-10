import "server-only";
import { EncryptJWT, jwtDecrypt } from "jose";

export const stateCookie = "__Host-website-oidc-state";
export const sessionCookie = "__Host-website-owner-session";

function sessionKey(): Uint8Array | null {
  const value = process.env.WEBSITE_CMS_SESSION_KEY;
  if (!value || !/^[A-Za-z0-9_-]{43}$/.test(value)) return null;
  const key = Buffer.from(value,"base64url");
  return key.byteLength === 32 ? new Uint8Array(key) : null;
}
export function sessionConfigured(): boolean { return sessionKey() !== null; }

export async function encryptOwnerCookie(
  kind: "oidc-state" | "owner-session", data: Record<string,string>, lifetime: number
): Promise<string> {
  const key=sessionKey();
  if (!key) throw new Error("Owner session encryption unavailable");
  return new EncryptJWT({kind,...data})
    .setProtectedHeader({alg:"dir",enc:"A256GCM"})
    .setIssuedAt().setExpirationTime(Math.min(lifetime,900)+"s")
    .encrypt(key);
}

export async function readOwnerCookie(
  request: Request, name: string, kind: "oidc-state" | "owner-session"
): Promise<Record<string,unknown>|null> {
  const key=sessionKey();
  if (!key) return null;
  const cookie=request.headers.get("cookie")?.split(";")
    .map(s=>s.trim()).find(s=>s.startsWith(name+"="))?.slice(name.length+1);
  if (!cookie || cookie.length > 6000) return null;
  try {
    const {payload}=await jwtDecrypt(decodeURIComponent(cookie),key,{
      keyManagementAlgorithms:["dir"],contentEncryptionAlgorithms:["A256GCM"],
      clockTolerance:"5s",
    });
    return payload.kind===kind ? payload as Record<string,unknown> : null;
  } catch { return null; }
}
export const secureCookie = {
  httpOnly:true, secure:true, sameSite:"lax" as const, path:"/",
};
