import {describe,expect,it} from "vitest";
import {parseAnalyticsEvent} from "../src/lib/analytics-contract";
import {parseConsentChoice} from "../src/lib/consent-server";

describe("versioned consent and minimal first-party analytics",()=>{
  it("accepts only independent optional boolean purposes",()=>{
    expect(parseConsentChoice({analytics:true,marketing:false})).toEqual({
      analytics:true,marketing:false,
    });
    expect(parseConsentChoice({analytics:"yes",marketing:true})).toBeNull();
    expect(parseConsentChoice({analytics:true})).toBeNull();
  });
  it("allows a short controlled event with a canonical page path",()=>{
    expect(parseAnalyticsEvent({
      eventName:"cta_click",actionKey:"cta_contact",routePath:"/content/example-page",
    })).toEqual({eventName:"cta_click",actionKey:"cta_contact",
      routePath:"/content/example-page"});
  });
  it("blocks PII, tracking IDs, query strings and arbitrary event payloads",()=>{
    const baseline={eventName:"cta_click",actionKey:"cta_contact",routePath:"/contact"};
    for(const value of [
      {...baseline,email:"person@example.org"},
      {...baseline,formFields:{phone:"12345"}},
      {...baseline,visitorId:"persistent-fingerprint"},
      {...baseline,routePath:"/contact?email=person@example.org"},
      {...baseline,routePath:"/owner"},
      {...baseline,routePath:"/content/../private"},
      {...baseline,eventName:"purchase"},
      {...baseline,actionKey:"person@example.org"},
      {...baseline,actionKey:"a".repeat(81)},
    ])expect(parseAnalyticsEvent(value)).toBeNull();
  });
});
