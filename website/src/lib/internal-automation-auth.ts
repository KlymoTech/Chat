import {createHmac,timingSafeEqual} from "node:crypto";
const body='{"operation":"advance-internal"}';
export function signInternalTick(secret:string,at=Date.now()):{
 body:string;headers:Record<string,string>
}{
  if(!secret||secret.length<32||!Number.isFinite(at))throw Error("Signing disabled");
  const timestamp=String(Math.floor(at/1000));
  const signature=createHmac("sha256",secret).update(timestamp+"."+body).digest("hex");
  return {body,headers:{"Content-Type":"application/json",
    "X-Automation-Timestamp":timestamp,
    "X-Automation-Signature":"sha256="+signature}};
}
export function verifyInternalTick(
 raw:string,headers:Headers,secret:string|undefined,now=Date.now(),
):boolean{
  if(!secret||secret.length<32||raw!==body)return false;
  const t=headers.get("x-automation-timestamp");
  const s=headers.get("x-automation-signature");
  if(!t||!/^[1-9][0-9]{9,11}$/.test(t)||!s||
     !/^sha256=[0-9a-f]{64}$/.test(s)||
     Math.abs(now/1000-Number(t))>120)return false;
  const expected=createHmac("sha256",secret).update(t+"."+body).digest();
  const actual=Buffer.from(s.slice(7),"hex");
  return actual.length===expected.length&&timingSafeEqual(actual,expected);
}
