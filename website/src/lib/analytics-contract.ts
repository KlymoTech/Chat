/** Strict, versioned first-party measurement vocabulary. Never accept arbitrary JSON. */
export const EVENT_NAMES=[
  "content_view","cta_click","navigation_click","faq_open","form_start",
] as const;
export type EventName=typeof EVENT_NAMES[number];
export type AnalyticsEvent=Readonly<{eventName:EventName;actionKey:string;routePath:string}>;
// Pair each event with its supported semantic action to avoid fabricated metrics.
// Form values, user identifiers and arbitrary UTM strings are not action keys.
const blockId="[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}";
const validAction:Record<EventName,RegExp>={
  content_view:/^page_view$/,
  cta_click:new RegExp("^cta_(?:contact|services|resources|"+blockId+")$"),
  navigation_click:/^nav_(?:home|services|about|resources|blog|contact)$/,
  faq_open:new RegExp("^faq_"+blockId+"_[0-9]{1,2}$"),
  form_start:/^form_start$/,
};
const route=/^\/(?:$|services$|about$|contact$|resources$|blog$|content\/[a-z0-9]+(?:-[a-z0-9]+)*)$/;
export function parseAnalyticsEvent(value:unknown):AnalyticsEvent|null {
  if(!value||typeof value!=="object"||Array.isArray(value))return null;
  const v=value as Record<string,unknown>;
  if(Object.keys(v).some(field=>!["eventName","actionKey","routePath"].includes(field)))
    return null;
  if(typeof v.eventName!=="string"||!EVENT_NAMES.includes(v.eventName as EventName) ||
     typeof v.actionKey!=="string"||!validAction[v.eventName as EventName].test(v.actionKey)||
     typeof v.routePath!=="string"||v.routePath.length>512||!route.test(v.routePath))
    return null;
  return {eventName:v.eventName as EventName,actionKey:v.actionKey,routePath:v.routePath};
}
