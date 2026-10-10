/** Conservative application of explicit browser sale/sharing opt-out preferences.
 * GPC does not automatically prohibit necessary processing or approved
 * strictly first-party analytics, and is not a blanket erasure request. */
export function hasGlobalPrivacyControl(headers:Headers):boolean{
  return headers.get("sec-gpc")==="1";
}
export function applyBrowserOptOut<T extends {analytics:boolean;marketing:boolean}>(
  requested:T,globalPrivacyControl:boolean,
):{analytics:boolean;marketing:boolean;gpcApplied:boolean}{
  return {analytics:requested.analytics,marketing:requested.marketing&&!globalPrivacyControl,
    gpcApplied:globalPrivacyControl};
}
