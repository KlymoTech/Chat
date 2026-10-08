"""Responsive UI smoke checks against an explicitly demo-only build.

This is visual/interaction evidence, NOT a live backend/provider integration test.
Run after VITE_DEMO_MODE=true npm run build. Production builds must not set it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'review-results' / 'browser'
OUT.mkdir(parents=True, exist_ok=True)
BASE = 'http://127.0.0.1:4173'
results: list[dict] = []
errors: list[str] = []
server_log = (OUT / 'server.log').open('w')
server = subprocess.Popen(['npm', 'run', 'preview', '--workspace', '@northstar/web', '--', '--host', '127.0.0.1', '--port', '4173', '--strictPort'], cwd=ROOT, stdout=server_log, stderr=subprocess.STDOUT)
try:
    for _ in range(90):
        try:
            with urllib.request.urlopen(BASE, timeout=1):
                break
        except (urllib.error.URLError, TimeoutError):
            time.sleep(1)
    else:
        raise RuntimeError('Preview server did not become ready')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={'width': 1392, 'height': 1000}, device_scale_factor=1, reduced_motion='reduce')
        # Every API request is an explicit offline demo fixture. No production
        # credentials, provider calls, customer data, or external writes are used.
        context.route('**/api/v1/**', lambda route: route.fulfill(status=503, content_type='application/json', body=json.dumps({'detail': 'Offline visual-review fixture'})))
        context.add_init_script("localStorage.setItem('northstar.session', JSON.stringify({ accessToken: 'demo.review.token', expiresAt: '2099-01-01T00:00:00.000Z', user: { id: 'review-user', name: 'Sam Review', email: 'review@example.test', role: 'owner', emailVerified: true } }));")
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            page.goto(BASE)
            expect(page.get_by_role('heading', name='Your agents')).to_be_visible(timeout=30000)
            expect(page.get_by_role('link', name='Open Northstar Guide')).to_be_visible(timeout=30000)
            page.evaluate('document.fonts.ready')
            for width in [1392, 1024, 768, 390, 360]:
                page.set_viewport_size({'width': width, 'height': 1000 if width == 1392 else 900})
                page.wait_for_timeout(150)
                actual = page.evaluate('document.documentElement.scrollWidth')
                page.screenshot(path=str(OUT / f'overview-{width}.png'), full_page=True)
                results.append({'check': f'overview-width-{width}', 'viewport': width, 'documentWidth': actual, 'passed': actual <= width})
                assert actual <= width, f'Horizontal overflow at {width}: {actual}'
            page.get_by_role('button', name='Open navigation').click()
            drawer = page.get_by_role('dialog', name='Main navigation')
            expect(drawer).to_be_visible()
            expect(drawer.get_by_role('link', name='Conversations', exact=True)).to_be_visible()
            page.screenshot(path=str(OUT / 'mobile-navigation.png'), full_page=True)
            page.keyboard.press('Escape')
            expect(drawer).not_to_be_visible()
            expect(page.get_by_role('button', name='Open navigation')).to_be_focused()
            results.append({'check': 'mobile-drawer-keyboard-focus', 'passed': True})
            page.set_viewport_size({'width': 1392, 'height': 1000})
            page.get_by_label('Chart period').select_option('30')
            page.get_by_role('button', name='Resolved', exact=True).click()
            expect(page.get_by_role('img', name='Resolved conversations trend')).to_be_visible(timeout=15000)
            page.keyboard.press('Control+k')
            expect(page.get_by_role('dialog', name='Search and commands')).to_be_visible()
            page.keyboard.press('Escape')
            results.append({'check': 'chart-and-command-search', 'passed': True})
            page.get_by_role('link', name='Create agent', exact=True).click()
            modal = page.get_by_role('dialog', name='Create an AI agent')
            expect(modal).to_be_visible()
            expect(modal.get_by_role('button', name='Continue', exact=True)).to_be_disabled()
            modal.get_by_label('Agent name', exact=True).fill('Review assistant')
            expect(modal.get_by_role('button', name='Continue', exact=True)).to_be_enabled()
            page.screenshot(path=str(OUT / 'agent-create-desktop.png'), full_page=True)
            page.set_viewport_size({'width': 390, 'height': 900})
            page.screenshot(path=str(OUT / 'agent-create-mobile.png'), full_page=True)
            modal.get_by_role('button', name='Cancel', exact=True).click()
            expect(modal).not_to_be_visible()
            assert 'create=1' not in page.url
            results.append({'check': 'existing-agent-wizard-deep-link-validation-cancel', 'passed': True})
            page.set_viewport_size({'width': 1392, 'height': 1000})
            for name, route in [('agents', '/agents'), ('conversations', '/conversations'), ('leads', '/leads'), ('education', '/education')]:
                page.goto(BASE + route)
                expect(page.locator('.saas-bot-shell')).to_be_visible(timeout=30000)
                page.wait_for_timeout(1500)
                page.screenshot(path=str(OUT / f'{name}-desktop.png'), full_page=True)
                results.append({'check': f'existing-route-{name}', 'passed': True})
            assert not errors, f'Uncaught browser errors: {errors}'
            results.append({'check': 'no-uncaught-browser-errors', 'passed': True})
        except Exception as error:
            page.screenshot(path=str(OUT / 'failure.png'), full_page=True)
            results.append({'check': 'execution', 'passed': False, 'error': str(error)})
            raise
        finally:
            browser.close()
finally:
    server.terminate()
    server.wait(timeout=15)
    server_log.close()
    (OUT / 'summary.json').write_text(json.dumps({'mode': 'demo-only visual review; not backend integration', 'githubSha': os.getenv('GITHUB_SHA'), 'results': results, 'pageErrors': errors}, indent=2))
