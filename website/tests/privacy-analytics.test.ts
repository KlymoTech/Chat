import {describe,expect,it,vi} from "vitest";
vi.mock("server-only",()=>({}));
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
  it("refuses unsanctioned action labels even when they contain no special characters",()=>{
    const base={eventName:"cta_click",actionKey:"cta_contact",routePath:"/contact"};
    expect(parseAnalyticsEvent({...base,actionKey:"johndoe1987"})).toBeNull();
    expect(parseAnalyticsEvent({...base,actionKey:"hidden_customer_identifier"})).toBeNull();
    expect(parseAnalyticsEvent({...base,
      actionKey:"cta_550e8400-e29b-41d4-a716-446655440000"})).not.toBeNull();
    expect(parseAnalyticsEvent({...base,eventName:"faq_open",
      actionKey:"faq_550e8400-e29b-41d4-a716-446655440000_3"})).not.toBeNull();
  });
  it("rejects mismatched event/action pairs that would inflate reporting",()=>{
    const base={eventName:"cta_click",actionKey:"cta_contact",routePath:"/contact"};
    expect(parseAnalyticsEvent({...base,eventName:"faq_open"})).toBeNull();
    expect(parseAnalyticsEvent({...base,eventName:"form_start"})).toBeNull();
    expect(parseAnalyticsEvent({...base,eventName:"navigation_click"})).toBeNull();
    expect(parseAnalyticsEvent({...base,eventName:"content_view"})).toBeNull();
    expect(parseAnalyticsEvent({...base,eventName:"faq_open",
      actionKey:"faq_550e8400-e29b-41d4-a716-446655440000_0"})).not.toBeNull();
    expect(parseAnalyticsEvent({...base,eventName:"form_start",
      actionKey:"form_start"})).not.toBeNull();
    expect(parseAnalyticsEvent({...base,eventName:"content_view",
      actionKey:"page_view"})).not.toBeNull();
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
