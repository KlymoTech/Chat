import { describe, expect, it } from "vitest";
import { parseLeadInput } from "../src/lib/lead-input";

const valid = () => ({
  idempotencyKey: "123e4567-e89b-42d3-a456-426614174000",
  fullName: "  Jane Doe  ",
  email: "  JANE@example.com  ",
  message: "  Interested in a demo  ",
  privacyAcknowledged: true,
});

describe("lead input security and normalization", () => {
  it("normalizes a valid acknowledged lead", () => {
    expect(parseLeadInput(valid())).toEqual({
      idempotencyKey: valid().idempotencyKey,
      fullName: "Jane Doe",
      email: "jane@example.com",
      message: "Interested in a demo",
      privacyAcknowledged: true,
    });
  });
  it("rejects unacknowledged leads", () => {
    expect(parseLeadInput({...valid(), privacyAcknowledged: false})).toBeNull();
  });
  it("rejects control characters in untrusted form fields", () => {
    for (const field of ["fullName", "email", "message"] as const) {
      expect(parseLeadInput({...valid(), [field]: valid()[field] + "\r\nX-Injected: 1"})).toBeNull();
      expect(parseLeadInput({...valid(), [field]: valid()[field] + "\u0000"})).toBeNull();
    }
  });
  it("rejects oversized messages and invalid idempotency keys", () => {
    expect(parseLeadInput({...valid(), message: "x".repeat(4001)})).toBeNull();
    expect(parseLeadInput({...valid(), idempotencyKey: "not-a-uuid"})).toBeNull();
  });
});
