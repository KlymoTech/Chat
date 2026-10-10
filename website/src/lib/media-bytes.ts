import {createHash} from "node:crypto";
import {MEDIA_MIME_ALLOWLIST, type MediaMime} from "./media-contract";

const maxBytes=10*1024*1024;
const png=Buffer.from([0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a]);

/**
 * Lightweight signature gate only, NOT an image parser, antivirus scanner or
 * CDR process. Quarantined files MUST never be served from this result alone.
 */
export function sniffQuarantinedImage(bytes:Uint8Array):MediaMime|null {
  if(bytes.byteLength<12||bytes.byteLength>maxBytes)return null;
  const b=Buffer.from(bytes.buffer,bytes.byteOffset,bytes.byteLength);
  if(b[0]===0xff&&b[1]===0xd8&&b[2]===0xff)return "image/jpeg";
  if(b.subarray(0,8).equals(png))return "image/png";
  if(b.toString("ascii",0,4)==="RIFF"&&b.toString("ascii",8,12)==="WEBP")
    return "image/webp";
  if(b.toString("ascii",4,8)==="ftyp" && b.length>=20) {
    const size=b.readUInt32BE(0);
    if(size>=16 && size<=b.byteLength) {
      const brands=b.subarray(8,Math.min(size,128)).toString("ascii");
      if(brands.includes("avif")||brands.includes("avis"))return "image/avif";
    }
  }
  return null;
}

export type VerifiedQuarantineBytes=Readonly<{sha256:string;byteSize:number;mime:MediaMime}>;
export function verifyQuarantinedBytes(
  bytes:Uint8Array,declared:{sha256:string;byteSize:number;mime:string},
):VerifiedQuarantineBytes|null {
  if(!Number.isSafeInteger(declared.byteSize)||declared.byteSize<1||
     declared.byteSize>maxBytes||bytes.byteLength!==declared.byteSize ||
     !/^[0-9a-f]{64}$/.test(declared.sha256) ||
     !MEDIA_MIME_ALLOWLIST.includes(declared.mime as MediaMime))return null;
  const mime=sniffQuarantinedImage(bytes);
  if(mime!==declared.mime)return null;
  const sha256=createHash("sha256").update(bytes).digest("hex");
  if(sha256!==declared.sha256)return null;
  return {sha256,byteSize:bytes.byteLength,mime};
}
