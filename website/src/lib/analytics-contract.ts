/** Strict, versioned first-party measurement vocabulary. Never accept arbitrary JSON. */
export const EVENT_NAMES=[
  "content_view","cta_click","navigation_click","faq_open","form_start",
] as const;
export type EventName=typeof EVENT_NAMES[number];
export type AnalyticsEvent=Readonly<{eventName:EventName;actionKey:string;routePath:string}>;
// Restrict action keys to a fixed action dictionary or sanctioned block IDs.
 // A generic free-text "action key" could smuggle names, emails or other PII.
const key=/^(?:cta_contact|cta_services|cta_resources|nav_home|nav_services|nav_about|nav_resources|nav_blog|nav_contact|page_view|form_start|cta_[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}|faq_[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}_[0-9]{1,2})$/;
const route=/^\/(?:$|services$|about$|contact$|resources$|blog$|content\/[a-z0-9]+(?:-[a-z0-9]+)*)$/;
export function parseAnalyticsEvent(value:unknown):AnalyticsEvent|null {
  if(!value||typeof value!=="object"||Array.isArray(value))return null;
  const v=value as Record<string,unknown>;
  if(Object.keys(v).some(field=>!["eventName","actionKey","routePath"].includes(field)))
    return null;
  if(typeof v.eventName!=="string"||!EVENT_NAMES.includes(v.eventName as EventName) ||
     typeof v.actionKey!=="string"||!key.test(v.actionKey)||
     typeof v.routePath!=="string"||v.routePath.length>512||!route.test(v.routePath))
    return null;
  return {eventName:v.eventName as EventName,actionKey:v.actionKey,routePath:v.routePath};
}
