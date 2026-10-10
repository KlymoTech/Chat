import {describe,expect,it} from "vitest";
import {
  approvedPublicStoreEndpoint,validatePublicMediaReference,
} from "../src/lib/media-delivery-contract";

const assetId="550e8400-e29b-41d4-a716-446655440000";
const siteId="62a2a2bf-1b2a-4fe2-a333-12b2a2a2a2a2";
const correct={
  id:assetId,storage_key:"processed/"+siteId+"/"+assetId+"/candidate.webp",
  sha256:"a".repeat(64),byte_size:"8192",
};
describe("published media delivery boundary",()=>{
  it("accepts only the requested UUID and matching sanitized candidate",()=>{
    expect(validatePublicMediaReference(correct,assetId)).toEqual({
      id:assetId,storageKey:correct.storage_key,sha256:correct.sha256,byteSize:8192,
    });
  });
  it("denies all original uploads, traversal, asset swaps and invalid checksums",()=>{
    for(const entry of [
      {...correct,storage_key:"quarantine/"+siteId+"/"+assetId+"/original"},
      {...correct,storage_key:"processed/"+siteId+"/../candidate.webp"},
      {...correct,storage_key:"processed/"+siteId+"/"+siteId+"/candidate.webp"},
      {...correct,id:siteId},
      {...correct,sha256:"broken"},
      {...correct,byte_size:"0"},
      {...correct,byte_size:"10485761"},
    ])expect(validatePublicMediaReference(entry,assetId)).toBeNull();
    expect(validatePublicMediaReference(correct,"../../../../etc/passwd")).toBeNull();
  });
  it("refuses unapproved or malformed storage endpoint configuration",()=>{
    expect(approvedPublicStoreEndpoint("https://media.example-company.com/"))
      .toBe("https://media.example-company.com");
    for(const url of [
      "http://media.example-company.com/",
      "https://127.0.0.1/",
      "https://localhost/",
      "https://10.0.0.1/",
      "https://169.254.169.254/",
      "https://storage.internal/",
      "https://media.example-company.com:9000/",
      "https://user:password@media.example-company.com/",
      "https://media.example-company.com/anything",
      "https://media.example-company.com/?token=secret",
    ])expect(approvedPublicStoreEndpoint(url)).toBeNull();
  });
});
