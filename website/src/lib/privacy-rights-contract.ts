/** Bounded, non-PII privacy rights case states. No automated erasure. */
export const RIGHT_KINDS=["access","correction","erasure","objection","restriction"] as const;
export type RightKind=typeof RIGHT_KINDS[number];
export const CASE_STATES=[
  "intake","pending_verification","verified","under_review",
  "legal_hold","approved","denied","in_execution","fulfilled",
] as const;
export type CaseState=typeof CASE_STATES[number];
export const CASE_REASONS=[
  "identity_requested","identity_confirmed","review_requested",
  "legal_review_required","lawful_hold_confirmed","hold_released",
  "scope_approved","policy_exception","execution_started",
  "execution_evidence_reviewed",
] as const;
export type CaseReason=typeof CASE_REASONS[number];
const transitions:Record<CaseState,readonly CaseState[]>={
  intake:["pending_verification","verified"],
  pending_verification:["verified"],
  verified:["under_review"],
  under_review:["approved","denied","legal_hold"],
  legal_hold:["under_review"],
  approved:["in_execution"],
  denied:[],
  in_execution:["fulfilled"],
  fulfilled:[],
};
export type CaseTransition=Readonly<{from:CaseState;to:CaseState;reason:CaseReason}>;
export function validCaseKind(value:unknown):value is RightKind{
  return typeof value==="string"&&RIGHT_KINDS.some(x=>x===value);
}
export function validCaseState(value:unknown):value is CaseState{
  return typeof value==="string"&&CASE_STATES.some(x=>x===value);
}
export function allowedCaseTransition(from:unknown,to:unknown,reason:unknown):boolean{
  if(!validCaseState(from)||!validCaseState(to)||
     typeof reason!=="string"||!CASE_REASONS.some(x=>x===reason))return false;
  if(!transitions[from].includes(to))return false;
  const expected:Partial<Record<CaseState,CaseReason>>={
    pending_verification:"identity_requested",verified:"identity_confirmed",
    under_review:from==="legal_hold"?"hold_released":"review_requested",
    legal_hold:"lawful_hold_confirmed",approved:"scope_approved",
    denied:"policy_exception",in_execution:"execution_started",
    fulfilled:"execution_evidence_reviewed",
  };
  return expected[to]===reason;
}
