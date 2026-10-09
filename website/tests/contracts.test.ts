import { describe, expect, it } from "vitest";
import { parseLeadInput } from "../src/lib/lead-input";
import { isPublishedPage } from "../src/lib/cms";
import { canonical, publishedOrigin } from "../src/lib/seo";
import { DENY_ALL, maySendOptionalEvent } from "../src/lib/consent-contract";

const lead = {
  idempotencyKey: "2b1a657d-e7c9-47bf-9c41-45408fc91aa2",
  fullName: "  Example User  ",
  email: "  Example@Example.com  ",
  message: "  Please contact me.  ",
  privacyAcknowledged: true,
};
describe("website lead intake contract", () => {
  it("normalizes accepted enquiry data", () => {
    expect(parseLeadInput(lead)).toEqual({
      ...lead, fullName: "Example User", email: "example@example.com",
      message: "Please contact me.",
    });
  });
  it("fails closed without acknowledgement or a valid retry key", () => {
    expect(parseLeadInput({...lead, privacyAcknowledged:false})).toBeNull();
    expect(parseLeadInput({...lead, idempotencyKey:"not-a-uuid"})).toBeNull();
    expect(parseLeadInput({...lead, message:" ".repeat(30)})).toBeNull();
  });
  it("enforces field length limits", () => {
    expect(parseLeadInput({...lead, fullName:"x".repeat(161)})).toBeNull();
    expect(parseLeadInput({...lead, message:"x".repeat(4001)})).toBeNull();
  });
});

const page = {
  id:"550e8400-e29b-41d4-a716-446655440000", path:"/content/intro", locale:"en", revision:1,
  title:"Introduction", description:"Published introduction",
  blocks:[{type:"heading",text:"Welcome"},{type:"callout",title:"Note",body:"Example"}],
};
describe("public CMS rendering contract", () => {
  it("accepts safe published block shapes", () => expect(isPublishedPage(page)).toBe(true));
  it("accepts safe image references and rejects untrusted image URLs", () => {
    const image={type:"image",assetId:"550e8400-e29b-41d4-a716-446655440000",
      alt:"Alt text for image",caption:"Optional caption"};
    expect(isPublishedPage({...page,blocks:[image]})).toBe(true);
    expect(isPublishedPage({...page,blocks:[{...image,assetId:"../../private"}]})).toBe(false);
    expect(isPublishedPage({...page,blocks:[{...image,assetId:"https://untrusted.example/image"}]})).toBe(false);
    expect(isPublishedPage({...page,blocks:[{...image,alt:""}]})).toBe(false);
    expect(isPublishedPage({...page,blocks:[{...image,caption:"x".repeat(501)}]})).toBe(false);
  });
  it("rejects executable HTML block types", () =>
    expect(isPublishedPage({...page,blocks:[{type:"html",html:"<script>alert(1)</script>"}]})).toBe(false));
  it("rejects oversized content, unsafe paths and excessive blocks", () => {
    expect(isPublishedPage({...page, path:"/content/../private"})).toBe(false);
    expect(isPublishedPage({...page, title:"x".repeat(181)})).toBe(false);
    expect(isPublishedPage({...page, blocks:Array.from({length:101}, () => ({type:"paragraph",text:"ok"}))})).toBe(false);
  });
  it("rejects invalid revisions and content containers", () => {
    expect(isPublishedPage({...page,revision:0})).toBe(false);
    expect(isPublishedPage({...page,blocks:{type:"heading"}})).toBe(false);
  });
});

describe("privacy and search defaults", () => {
  it("denies analytics and marketing until a purpose is granted", () => {
    expect(maySendOptionalEvent("analytics",DENY_ALL)).toBe(false);
    expect(maySendOptionalEvent("marketing",DENY_ALL)).toBe(false);
  });
  it("denies search indexing without explicit HTTPS production approval", () => {
    const priorUrl = process.env.NEXT_PUBLIC_SITE_URL;
    const priorApproval = process.env.NEXT_PUBLIC_SITE_APPROVED;
    try {
      process.env.NEXT_PUBLIC_SITE_URL = "http://localhost:3000";
      process.env.NEXT_PUBLIC_SITE_APPROVED = "true";
      expect(publishedOrigin()).toBeNull();
      expect(canonical("/")).toBeUndefined();
      process.env.NEXT_PUBLIC_SITE_URL = "https://example.org/";
      process.env.NEXT_PUBLIC_SITE_APPROVED = "false";
      expect(publishedOrigin()).toBeNull();
    } finally {
      if(priorUrl === undefined) delete process.env.NEXT_PUBLIC_SITE_URL;
      else process.env.NEXT_PUBLIC_SITE_URL=priorUrl;
      if(priorApproval === undefined) delete process.env.NEXT_PUBLIC_SITE_APPROVED;
      else process.env.NEXT_PUBLIC_SITE_APPROVED=priorApproval;
    }
  });
});
