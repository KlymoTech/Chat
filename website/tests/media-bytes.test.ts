import {createHash} from "node:crypto";
import {describe,expect,it} from "vitest";
import {sniffQuarantinedImage,verifyQuarantinedBytes} from "../src/lib/media-bytes";

const png=Uint8Array.from([
  0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a,
  0x00,0x00,0x00,0x0d,0x49,0x48,0x44,0x52,
]);
const webp=Uint8Array.from([0x52,0x49,0x46,0x46,0x08,0x00,0x00,0x00,0x57,0x45,0x42,0x50]);
const jpeg=Uint8Array.from([0xff,0xd8,0xff,0xe0,0x00,0x10,0x4a,0x46,0x49,0x46,0x00,0x01]);
const avif=Uint8Array.from([
  0x00,0x00,0x00,0x14,0x66,0x74,0x79,0x70,0x61,0x76,0x69,0x66,
  0x00,0x00,0x00,0x00,0x6d,0x69,0x66,0x31,
]);
function manifest(bytes:Uint8Array,mime:string){
  return {sha256:createHash("sha256").update(bytes).digest("hex"),byteSize:bytes.byteLength,mime};
}

describe("quarantine image signature checks",()=>{
  it("recognizes only allowlisted file signatures",()=>{
    expect(sniffQuarantinedImage(png)).toBe("image/png");
    expect(sniffQuarantinedImage(webp)).toBe("image/webp");
    expect(sniffQuarantinedImage(jpeg)).toBe("image/jpeg");
    expect(sniffQuarantinedImage(avif)).toBe("image/avif");
    expect(sniffQuarantinedImage(new TextEncoder().encode("<svg><script>alert(1)</script></svg>"))).toBeNull();
  });
  it("enforces the exact manifest checksum, byte count and content type",()=>{
    expect(verifyQuarantinedBytes(png,manifest(png,"image/png"))).toEqual({
      sha256:manifest(png,"image/png").sha256,byteSize:png.byteLength,mime:"image/png",
    });
    expect(verifyQuarantinedBytes(png,manifest(png,"image/jpeg"))).toBeNull();
    expect(verifyQuarantinedBytes(png,{...manifest(png,"image/png"),sha256:"0".repeat(64)})).toBeNull();
    expect(verifyQuarantinedBytes(png,{...manifest(png,"image/png"),byteSize:png.length+1})).toBeNull();
  });
  it("denies empty or oversized bodies",()=>{
    expect(sniffQuarantinedImage(new Uint8Array(0))).toBeNull();
    expect(verifyQuarantinedBytes(new Uint8Array(0),{
      sha256:"a".repeat(64),byteSize:0,mime:"image/png",
    })).toBeNull();
    expect(sniffQuarantinedImage(new Uint8Array(10*1024*1024+1))).toBeNull();
  });
  it("never treats a signature check as an approval/scanner receipt",()=>{
    const validated=verifyQuarantinedBytes(webp,manifest(webp,"image/webp"));
    expect(validated).not.toBeNull();
    expect(validated).not.toHaveProperty("approved");
    expect(validated).not.toHaveProperty("scanned");
    expect(validated).not.toHaveProperty("publicUrl");
  });
});
