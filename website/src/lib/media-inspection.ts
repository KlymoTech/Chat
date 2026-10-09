import "server-only";
import {createConnection} from "node:net";
import {createHash} from "node:crypto";
import sharp from "sharp";
import {sniffQuarantinedImage} from "./media-bytes";

const maxBytes=10*1024*1024;
function clamdPort():number {
  const raw=process.env.WEBSITE_MEDIA_CLAMD_PORT;
  const port=raw?Number(raw):3310;
  if(process.env.WEBSITE_MEDIA_SCAN_ENABLED!=="true" ||
     !Number.isSafeInteger(port)||port<1024||port>65535)
    throw new Error("Local ClamAV scanning unavailable");
  return port;
}

/** ClamAV INSTREAM, loopback ONLY. Every unknown or missing response is denial. */
export async function scanWithLocalClamAv(bytes:Uint8Array):Promise<void> {
  const port=clamdPort();
  if(bytes.byteLength<12||bytes.byteLength>maxBytes)throw new Error("Invalid scan bytes");
  await new Promise<void>((resolve,reject)=>{
    const socket=createConnection({host:"127.0.0.1",port});
    let response="",settled=false;
    const finish=(error?:Error)=>{
      if(settled)return;
      settled=true;socket.destroy();
      if(error)reject(error);else resolve();
    };
    socket.setTimeout(20000);
    socket.on("error",()=>finish(new Error("Malware scanner unavailable")));
    socket.on("timeout",()=>finish(new Error("Malware scanner timeout")));
    socket.on("close",()=>{if(!settled)finish(new Error("Malware scanner closed without verdict"));});
    socket.on("data",(chunk:Buffer)=>{
      response+=chunk.toString("utf8");
      if(response.length>200)return finish(new Error("Invalid scanner response"));
      if(response.includes("\0")||response.includes("\n")){
        const verdict=response.split(/[\0\r\n]/,1)[0];
        if(verdict==="stream: OK")finish();
        else finish(new Error("Malware scanner did not approve the input"));
      }
    });
    socket.on("connect",()=>{
      socket.write("zINSTREAM\0");
      for(let at=0;at<bytes.byteLength;at+=64*1024){
        const block=bytes.subarray(at,at+64*1024);
        const length=Buffer.alloc(4);
        length.writeUInt32BE(block.length);
        socket.write(length);socket.write(block);
      }
      socket.write(Buffer.alloc(4));
    });
  });
}
export type InspectedImage = Readonly<{
  originalMime:string;originalSha256:string;originalSize:number;
  width:number;height:number;sanitized:Buffer;sanitizedSha256:string;
  scanEngine:"clamav-instream";scannerReceiptSha256:string;
}>;

/** Decode to pixels and re-encode to strip EXIF, ICC and embedded metadata. */
export async function inspectQuarantinedImage(bytes:Uint8Array):Promise<InspectedImage> {
  if(bytes.byteLength<12||bytes.byteLength>maxBytes)throw new Error("Invalid input size");
  const originalMime=sniffQuarantinedImage(bytes);
  if(!originalMime)throw new Error("Unknown input type");
  await scanWithLocalClamAv(bytes);
  const image=sharp(Buffer.from(bytes),{
    failOn:"error",limitInputPixels:25_000_000,animated:false,
  });
  const metadata=await image.metadata();
  if(!metadata.width||!metadata.height ||metadata.width>10000||
     metadata.height>10000||metadata.pages&&metadata.pages>1 ||
     metadata.width*metadata.height>25_000_000)
    throw new Error("Unsupported image dimensions or animation");
  const formats:{[key:string]:string}={
    jpeg:"image/jpeg",png:"image/png",webp:"image/webp",
    avif:"image/avif",heif:"image/avif",
  };
  if(formats[metadata.format]!==originalMime)throw new Error("Image decoder and signature disagree");
  // No withMetadata() call: orientation is baked into the pixels by rotate().
  const sanitized=await image.rotate().resize(2048,2048,{
    fit:"inside",withoutEnlargement:true,
  }).webp({quality:82,effort:4}).toBuffer();
  if(sanitized.length===0||sanitized.length>maxBytes)
    throw new Error("Derivative exceeds private processing policy");
  await scanWithLocalClamAv(sanitized);
  const originalSha256=createHash("sha256").update(bytes).digest("hex");
  const sanitizedSha256=createHash("sha256").update(sanitized).digest("hex");
  const scannerReceiptSha256=createHash("sha256")
    .update(JSON.stringify({originalSha256,sanitizedSha256,scanEngine:"clamav-instream",verdict:"clean"}))
    .digest("hex");
  return {originalMime,originalSha256,originalSize:bytes.byteLength,
    width:metadata.width,height:metadata.height,
    sanitized,sanitizedSha256,scanEngine:"clamav-instream",scannerReceiptSha256};
}
