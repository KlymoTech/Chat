import { describe, expect, it } from "vitest";
import { assertManualPreservationOnly, parseManualPreservationIntent } from "../src/lib/preservation-contract";
import { actorFromVerifiedClaims } from "../src/lib/owner-claims";

const site="550e8400-e29b-41d4-a716-446655440000";
const actor="62a2a2bf-1b2a-4fe2-a333-12b2a2a2a2a2";
describe("Chapter 38 source-content preservation", () => {
  it("allows only human trash/restore intents with reason", () => {
    expect(parseManualPreservationIntent({action:"trash",reason:"  Outdated public guidance  "})).toEqual({
      action:"trash",reason:"Outdated public guidance"
    });
    expect(parseManualPreservationIntent({action:"restore",reason:"Reinstate for content review"})).toEqual({
      action:"restore",reason:"Reinstate for content review"
    });
  });
  it("rejects purge, auto-expiry and insufficient reasons", () => {
    for(const input of [
      {action:"purge",reason:"Requested by operator"},
      {action:"expire",reason:"Content is older than one year"},
      {action:"trash",reason:"short"},
      {action:"trash",reason:"x".repeat(501)},
      {action:"restore"},
      null
    ]) expect(parseManualPreservationIntent(input)).toBeNull();
  });
  it("fails closed if no explicit false auto-delete setting exists", () => {
    expect(() => assertManualPreservationOnly("false")).not.toThrow();
    expect(() => assertManualPreservationOnly("true")).toThrow();
    expect(() => assertManualPreservationOnly(undefined)).toThrow();
  });
  it("never grants preservation permissions from unapproved claims", () => {
    expect(actorFromVerifiedClaims({sub:actor,site_id:site,permissions:["cms:trash"]},site)?.permissions).toEqual(["cms:trash"]);
    expect(actorFromVerifiedClaims({sub:actor,site_id:site,permissions:["cms:purge"]},site)).toBeNull();
    expect(actorFromVerifiedClaims({sub:actor,site_id:site,permissions:["cms:trash"]},"2d495e1d-bc02-4ddb-a972-d60e2b6c3de5")).toBeNull();
  });
});
