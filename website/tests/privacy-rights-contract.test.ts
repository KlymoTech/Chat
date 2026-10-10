import {describe,expect,it} from "vitest";
import {
  allowedCaseTransition,validCaseKind,validCaseState,
} from "../src/lib/privacy-rights-contract";
describe("privacy rights workflow contract",()=>{
  it("requires verified identity before review and approval",()=>{
    expect(validCaseKind("erasure")).toBe(true);
    expect(validCaseKind("automatically_delete_everything")).toBe(false);
    expect(validCaseState("legal_hold")).toBe(true);
    expect(allowedCaseTransition("intake","approved","scope_approved")).toBe(false);
    expect(allowedCaseTransition("intake","fulfilled","execution_evidence_reviewed")).toBe(false);
    expect(allowedCaseTransition("intake","pending_verification","identity_requested"))
      .toBe(true);
    expect(allowedCaseTransition("pending_verification","verified","identity_confirmed"))
      .toBe(true);
    expect(allowedCaseTransition("verified","under_review","review_requested"))
      .toBe(true);
  });
  it("permits manual legal hold and independently reviewed resumption",()=>{
    expect(allowedCaseTransition("under_review","legal_hold","lawful_hold_confirmed"))
      .toBe(true);
    expect(allowedCaseTransition("legal_hold","under_review","hold_released"))
      .toBe(true);
    expect(allowedCaseTransition("legal_hold","approved","scope_approved"))
      .toBe(false);
    expect(allowedCaseTransition("under_review","approved","scope_approved"))
      .toBe(true);
    expect(allowedCaseTransition("under_review","denied","policy_exception"))
      .toBe(true);
    expect(allowedCaseTransition("approved","in_execution","execution_started"))
      .toBe(true);
    expect(allowedCaseTransition("in_execution","fulfilled",
      "execution_evidence_reviewed")).toBe(true);
  });
  it("does not allow fabricated completion, reopening or arbitrary codes",()=>{
    expect(allowedCaseTransition("intake","fulfilled","execution_evidence_reviewed"))
      .toBe(false);
    expect(allowedCaseTransition("denied","intake","identity_requested")).toBe(false);
    expect(allowedCaseTransition("fulfilled","under_review","review_requested"))
      .toBe(false);
    expect(allowedCaseTransition("under_review","denied","arbitrary text")).toBe(false);
    expect(allowedCaseTransition("intake","verified","identity_requested"))
      .toBe(false);
  });
});
