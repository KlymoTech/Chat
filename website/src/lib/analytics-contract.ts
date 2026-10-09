/** Strict, versioned first-party measurement vocabulary. Never accept arbitrary JSON. */
export const EVENT_NAMES=[
  "content_view","cta_click","navigation_click","faq_open","form_start",
] as const;
export type EventName=typeof EVENT_NAMES[number];
export type AnalyticsEvent=Readonly<{eventName:EventName;actionKey:string;routePath:string}>;
const key=/^[a-z0-9_-]{1,80}$/;
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
