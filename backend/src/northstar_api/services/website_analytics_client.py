"""Small first-party browser collector, delivered from the same API origin.

It never emits an event until the consent API confirms the analytics purpose.
No URL query string, form value, identity or free text is collected.
"""
SITE_ANALYTICS_CLIENT_JS = r"""
(() => {
  'use strict';
  const script = document.currentScript;
  if (!script || typeof fetch !== 'function' || !crypto.randomUUID) return;
  const workspaceId = script.dataset.siteWorkspace || '';
  const slug = script.dataset.siteSlug || '';
  const apiPrefix = script.dataset.apiPrefix || '/api/v1';
  if (!/^[0-9a-fA-F-]{36}$/.test(workspaceId) || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug)) return;
  if (!/^\/[A-Za-z0-9/_-]+$/.test(apiPrefix)) return;
  const scope = apiPrefix.replace(/\/$/, '');
  let allowed = false;
  let pageSent = false;
  const endpoint = scope + '/site-analytics/' + encodeURIComponent(workspaceId) + '/events';

  function emit(eventType, blockId) {
    if (!allowed) return;
    const payload = { eventId: crypto.randomUUID(), eventType, slug };
    if (blockId) payload.blockId = blockId;
    fetch(endpoint, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify(payload),
      keepalive: true
    }).catch(() => {});
  }

  function visiblePage() {
    if (!allowed || pageSent || document.visibilityState !== 'visible') return;
    pageSent = true;
    emit('page_view');
  }

  document.addEventListener('click', (event) => {
    if (!allowed || !event.target || typeof event.target.closest !== 'function') return;
    const target = event.target.closest('a.site-action[data-builder-id]');
    if (!target) return;
    const blockId = target.getAttribute('data-builder-id') || '';
    if (/^[A-Za-z0-9_-]{1,80}$/.test(blockId)) emit('cta_click', blockId);
  }, { passive: true });
  document.addEventListener('visibilitychange', visiblePage);

  fetch(scope + '/site-consent/' + encodeURIComponent(workspaceId), {
    credentials: 'same-origin', headers: { 'Accept': 'application/json' }
  }).then((response) => response.ok ? response.json() : null)
    .then((preferences) => {
      allowed = preferences !== null && preferences.analytics === true;
      visiblePage();
    }).catch(() => { allowed = false; });
})();
"""
