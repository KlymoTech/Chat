import {describe,expect,it} from "vitest";
import {MEDIA_MIME_ALLOWLIST,parseMediaManifest} from "../src/lib/media-contract";

const valid={
  originalFilename:"product-banner.webp",
  claimedMime:"image/webp",
  claimedSha256:"a".repeat(64),
  claimedByteSize:16384,
  altDefault:"Accessible product banner",
  rightsStatement:"Original artwork owned by publisher",
  provenance:{source:"original",credit:"Site design team",generationTool:""},
};

describe("quarantined media intake contract",()=>{
  it("accepts bounded non-active image metadata without granting approval",()=>{
    expect(parseMediaManifest(valid)).toEqual(valid);
    expect(MEDIA_MIME_ALLOWLIST).not.toContain("image/svg+xml");
  });
  it("rejects active content and MIME/extension mismatches",()=>{
    for(const sample of [
      {...valid,originalFilename:"unsafe.svg"},
      {...valid,claimedMime:"image/svg+xml"},
      {...valid,originalFilename:"file.html",claimedMime:"image/png"},
      {...valid,originalFilename:"photo.png",claimedMime:"image/webp"},
      {...valid,originalFilename:"../photo.webp"},
      {...valid,originalFilename:"photo\\test.webp"},
      {...valid,originalFilename:".hidden.webp"},
      {...valid,originalFilename:"<script>.webp"},
    ])expect(parseMediaManifest(sample)).toBeNull();
  });
  it("rejects excessive files, invalid checksums and forged fields",()=>{
    expect(parseMediaManifest({...valid,claimedByteSize:10485761})).toBeNull();
    expect(parseMediaManifest({...valid,claimedByteSize:0})).toBeNull();
    expect(parseMediaManifest({...valid,claimedByteSize:2.5})).toBeNull();
    expect(parseMediaManifest({...valid,claimedSha256:"broken"})).toBeNull();
    expect(parseMediaManifest({...valid,altDefault:"a".repeat(301)})).toBeNull();
    expect(parseMediaManifest({...valid,rightsStatement:"a".repeat(501)})).toBeNull();
  });
  it("requires licensed credit and AI provenance without deleting declarations",()=>{
    expect(parseMediaManifest({...valid,provenance:{
      source:"licensed",credit:"",generationTool:""
    }})).toBeNull();
    expect(parseMediaManifest({...valid,provenance:{
      source:"ai-generated",credit:"",generationTool:""
    }})).toBeNull();
    expect(parseMediaManifest({...valid,provenance:{
      source:"ai-generated",credit:"Design team",generationTool:"Approved generator v1"
    }})?.provenance.generationTool).toBe("Approved generator v1");
  });
});
