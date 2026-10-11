"""Leads design export: normal frontend -> real FastAPI -> disposable SQLite browser regression.

Run only with APP_ENV=test FIGMA_LIVE_REVIEW=1, after a non-demo npm build.
This runner never accepts a deployment URL. It starts its own loopback server,
seeds synthetic records, and discards its database. It does not test PostgreSQL,
worker topology, real messaging delivery, billing or AI providers.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "review-results" / "leads-browser"
BASE = "http://127.0.0.1:4187"


def require_isolation() -> None:
    if (
        os.environ.get("APP_ENV") != "test"
        or os.environ.get("FIGMA_LIVE_REVIEW") != "1"
    ):
        raise RuntimeError("Explicit APP_ENV=test and FIGMA_LIVE_REVIEW=1 are required")
    if os.environ.get("VITE_DEMO_MODE", "false") != "false":
        raise RuntimeError("This test must not use a demo build")
    if not (ROOT / "frontend/dist/index.html").is_file():
        raise RuntimeError("Build the normal frontend before running the review")


def serve() -> None:
    """Add only static-file delivery after the application's actual API routes."""
    import uvicorn
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    from northstar_api.main import app

    dist = (ROOT / "frontend/dist").resolve()

    @app.get("/__review_probe", include_in_schema=False)
    async def probe():
        return {"run": os.environ["FIGMA_REVIEW_RUN"]}

    @app.get("/{asset:path}", include_in_schema=False)
    async def frontend(asset: str):
        if asset.startswith(("api/", "v1/")):
            raise HTTPException(404)
        candidate = (dist / asset).resolve()
        if not candidate.is_relative_to(dist):
            raise HTTPException(404)
        if candidate.is_file():
            return FileResponse(candidate)
        if asset.startswith("assets/"):
            raise HTTPException(404)
        return FileResponse(dist / "index.html")

    uvicorn.run(app, host="127.0.0.1", port=4187, log_level="warning")


def api(
    path: str, *, method: str = "GET", body=None, token: str = "", workspace: str = ""
):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if workspace:
        headers["X-Workspace-ID"] = workspace
    request = urllib.request.Request(
        BASE + "/api/v1/" + path,
        headers=headers,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


async def seed(scopes: list[dict]) -> dict:
    # All records are synthetic and are created through the real application API.
    status, session = api(
        "auth/login",
        method="POST",
        body={
            "email": os.environ["SEED_ADMIN_EMAIL"],
            "password": os.environ["SEED_ADMIN_PASSWORD"],
        },
    )
    assert status == 200
    token = session["accessToken"]
    leads = {}
    for name in reversed(
        [
            "Arjun Mehta",
            "Meera Shah",
            "Rahul Verma",
            "Ananya Rao",
            "Karan Patel",
            "Sneha Reddy",
        ]
    ):
        status, lead = api(
            "leads",
            method="POST",
            token=token,
            workspace=scopes[0]["workspace"]["id"],
            body={
                "agentId": scopes[0]["agent"]["id"],
                "name": name,
                "email": name.lower().replace(" ", ".") + "@example.com",
                "phone": "+919876543210",
                "consent": name != "Ananya Rao",
                "fields": {"company": "Example Labs", "location": "Mumbai, India"},
            },
        )
        assert status == 201, lead
        leads[name] = lead
    for name, stage in [
        ("Rahul Verma", "qualified"),
        ("Karan Patel", "converted"),
        ("Meera Shah", "contacted"),
    ]:
        assert (
            api(
                f"leads/{leads[name]['id']}",
                method="PATCH",
                token=token,
                workspace=scopes[0]["workspace"]["id"],
                body={"status": stage},
            )[0]
            == 200
        )
    return leads


def run_browser(
    scopes: list[dict],
    ids: dict,
    email: str,
    password: str,
    token: str,
    results: list,
    responses: list,
    page_errors: list,
) -> None:
    from urllib.parse import urlparse

    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1440, "height": 1218},
            reduced_motion="reduce",
            accept_downloads=True,
        )
        context.route(
            "**/*",
            lambda route: (
                route.continue_()
                if urlparse(route.request.url).hostname == "127.0.0.1"
                else route.abort()
            ),
        )
        page = context.new_page()
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on(
            "response",
            lambda r: (
                responses.append(
                    {
                        "method": r.request.method,
                        "path": urlparse(r.url).path,
                        "status": r.status,
                    }
                )
                if "/api/" in r.url
                else None
            ),
        )

        def passed(name):
            results.append({"check": name, "passed": True})
            print(f"PASS {name}", flush=True)

        def capture(name):
            page.evaluate("document.fonts.ready")
            page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)

        def choose_workspace(name):
            page.locator(".workspace-switcher__button").click()
            page.locator(".workspace-switcher__list button").filter(
                has_text=name
            ).click()
            expect(page.locator(".workspace-switcher__button")).to_contain_text(name)

        try:
            page.goto(BASE + "/login")
            page.get_by_label("Work email", exact=True).fill(email)
            page.get_by_label("Password", exact=True).fill(password)
            page.get_by_role("button", name="Sign in", exact=True).click()
            expect(page.locator(".saas-bot-shell")).to_be_visible(timeout=30000)
            choose_workspace(scopes[0]["workspace"]["name"])
            page.goto(BASE + "/leads")
            expect(
                page.get_by_role("button", name="Arjun Mehta", exact=True)
            ).to_be_visible(timeout=20000)
            expect(page.locator(".ld-metric").first.locator("strong")).to_have_text("6")
            expect(page.locator(".ld-table tbody tr")).to_have_count(6)
            passed("real-login-and-six-server-backed-leads-with-real-summary")
            capture("leads-desktop")
            for width in [1024, 768, 390, 360]:
                page.set_viewport_size({"width": width, "height": 900})
                # Responsive shell controls animate width. Measure the settled layout,
                # not an intermediate search-pill width immediately after a resize.
                page.wait_for_timeout(300)
                # Wait for the responsive layout to settle before measuring,
                # without suppressing or weakening the overflow assertion.
                page.wait_for_function("""() => {
                    const el = document.querySelector('.ld-table-scroll');
                    return !!el && el.getBoundingClientRect().width > 0;
                }""", timeout=5000)
                actual = page.evaluate("document.documentElement.scrollWidth")
                if actual > width:
                    offenders = page.evaluate(
                        """() => [...document.querySelectorAll('*')].map(e => ({tag:e.tagName,cls:e.className,right:e.getBoundingClientRect().right,width:e.getBoundingClientRect().width,overflow:getComputedStyle(e).overflow})).filter(e => e.right > innerWidth + 1)"""
                    )
                    (OUT / f"overflow-{width}.json").write_text(
                        json.dumps({"viewport": width, "documentWidth": actual, "ancestors": page.evaluate("""() => { const table = document.querySelector('.ld-table'); return table ? [table, ...(() => { const a=[]; let e=table.parentElement; while(e){a.push(e);e=e.parentElement}return a })()].map(e=>({tag:e.tagName, className:typeof e.className==='string'?e.className:'', width:e.getBoundingClientRect().width, scrollWidth:e.scrollWidth, clientWidth:e.clientWidth, overflowX:getComputedStyle(e).overflowX, minWidth:getComputedStyle(e).minWidth, display:getComputedStyle(e).display})) : [] }"""), "offenders": offenders}, indent=2)
                    )
                if actual > width:
                    # Include the actual out-of-flow box geometry and nearest
                    # scroll/containing ancestors in the saved CI artifact.
                    geometry = page.evaluate("""() => [...document.querySelectorAll('*')]
                      .filter(e => e.getBoundingClientRect().right > innerWidth + 1)
                      .slice(0, 60).map(e => ({
                        tag:e.tagName, cls:typeof e.className==='string'?e.className:'',
                        text:(e.textContent||'').trim().slice(0,45),
                        left:e.getBoundingClientRect().left, right:e.getBoundingClientRect().right,
                        position:getComputedStyle(e).position,
                        overflowX:getComputedStyle(e).overflowX,
                        parent:e.parentElement?.className || ''
                      }))""")
                    (OUT / f"geometry-{width}.json").write_text(json.dumps(geometry, indent=2))
                assert actual <= width, (
                    f"Settled horizontal overflow at {width}: {actual}"
                )
                capture(f"leads-{width}")
                passed(f"responsive-leads-{width}-no-document-overflow")
            page.set_viewport_size({"width": 1440, "height": 1218})
            page.get_by_role("button", name="Arjun Mehta", exact=True).click()
            drawer = page.get_by_role(
                "dialog", name="Lead details: Arjun Mehta", exact=True
            )
            expect(drawer).to_be_visible()
            expect(drawer).to_contain_text("arjun.mehta@example.com")
            capture("lead-detail")
            drawer.get_by_role("button", name="Change", exact=False).click()
            modal = page.get_by_role("dialog", name="Change lead status", exact=True)
            modal.get_by_role("radio", name=re.compile("Qualified")).check()
            modal.get_by_label("Reason / note", exact=True).fill(
                "Synthetic review: budget confirmed"
            )
            capture("lead-status")
            modal.get_by_role("button", name="Update status", exact=True).click()
            expect(modal).not_to_be_visible()
            expect(drawer.locator(".ld-current-stage")).to_contain_text("Qualified")
            assert (
                api(
                    f"leads/{ids['Arjun Mehta']['id']}/workspace",
                    token=token,
                    workspace=scopes[0]["workspace"]["id"],
                )[1]["lead"]["status"]
                == "qualified"
            )
            passed("stage-change-through-real-domain-api-and-reloaded-data")
            drawer.get_by_role("button", name="Assign", exact=True).click()
            modal = page.get_by_role("dialog", name="Assign lead", exact=True)
            modal.get_by_role("radio", name=re.compile("Browser Review")).check()
            modal.get_by_label("Assignment note", exact=True).fill(
                "Synthetic handover context"
            )
            capture("lead-assignment")
            modal.get_by_role(
                "button", name="Assign to Browser Review", exact=True
            ).click()
            expect(modal).not_to_be_visible()
            page.reload()
            expect(page.locator(".ld-owner")).to_contain_text(
                "Browser Review", timeout=15000
            )
            passed("assigned-owner-and-note-survive-full-reload")
            drawer = page.get_by_role(
                "dialog", name="Lead details: Arjun Mehta", exact=True
            )
            drawer.get_by_role("button", name="Follow-up", exact=True).click()
            modal = page.get_by_role("dialog", name="Schedule follow-up", exact=True)
            modal.get_by_label("Follow-up title", exact=True).fill(
                "Product demo follow-up"
            )
            capture("lead-followup")
            modal.get_by_role("button", name="Schedule follow-up", exact=True).click()
            expect(modal).not_to_be_visible()
            expect(drawer.locator(".ld-followup-list")).to_contain_text(
                "Product demo follow-up"
            )
            with page.expect_download() as download:
                drawer.get_by_role("button", name="Calendar", exact=True).click()
            calendar = Path(download.value.path()).read_text()
            assert "BEGIN:VCALENDAR" in calendar and "BEGIN:VALARM" in calendar
            assert "SUMMARY:Product demo follow-up" in calendar
            (OUT / "synthetic-reminder.ics").write_text(calendar)
            status, stored = api(
                f"leads/{ids['Arjun Mehta']['id']}/workspace",
                token=token,
                workspace=scopes[0]["workspace"]["id"],
            )
            assert (
                status == 200
                and stored["followUps"][0]["title"] == "Product demo follow-up"
                and stored["version"] == 2
            )
            passed("durable-followup-and-real-calendar-download-not-outbound-messaging")
            drawer.get_by_role("button", name="Sync to CRM", exact=True).click()
            modal = page.get_by_role("dialog", name="Sync lead to CRM", exact=True)
            expect(modal).to_contain_text("No CRM is connected")
            expect(
                modal.get_by_role("button", name="Sync lead", exact=True)
            ).to_be_disabled()
            capture("lead-sync-no-connection")
            modal.get_by_role("button", name="Close dialog", exact=True).click()
            drawer.get_by_role("button", name="Close lead details", exact=True).click()
            passed("crm-unconnected-state-never-claims-fake-sync-success")
            page.get_by_role("button", name="Add Lead", exact=True).click()
            modal = page.get_by_role("dialog", name="Add Lead", exact=True)
            expect(modal.get_by_role("checkbox")).not_to_be_checked()
            modal.get_by_label("Full name", exact=True).fill("New Browser Prospect")
            modal.get_by_label("Email", exact=True).fill("browser.prospect@example.com")
            modal.get_by_label("Assigned AI agent", exact=True).select_option(
                scopes[0]["agent"]["id"]
            )
            modal.get_by_role("button", name="Add Lead", exact=True).click()
            expect(modal).not_to_be_visible()
            new_drawer = page.get_by_role(
                "dialog", name="Lead details: New Browser Prospect", exact=True
            )
            expect(new_drawer).to_be_visible()
            expect(new_drawer.locator(".ld-telemetry")).to_contain_text("Not recorded")
            new_drawer.get_by_role(
                "button", name="Close lead details", exact=True
            ).click()
            passed("add-lead-uses-existing-api-with-consent-false-by-default")
            page.get_by_label("Search leads", exact=True).fill("Arjun")
            expect(page.locator(".ld-table tbody tr")).to_have_count(1)
            with page.expect_download() as download:
                page.get_by_role("button", name="Export CSV", exact=True).click()
            exported = Path(download.value.path()).read_text(encoding="utf-8-sig")
            assert (
                "arjun.mehta@example.com" in exported
                and "browser.prospect@example.com" not in exported
            )
            passed("search-and-filtered-full-dataset-csv-use-real-backend")
            choose_workspace(scopes[1]["workspace"]["name"])
            expect(
                page.get_by_role("heading", name="No leads found", exact=True)
            ).to_be_visible(timeout=20000)
            expect(page.locator(".ld-metric").first.locator("strong")).to_have_text("0")
            assert not page.get_by_text("arjun.mehta@example.com", exact=True).count()
            passed("workspace-switch-does-not-expose-other-workspace-leads")
            assert not page_errors, page_errors
            assert not [r for r in responses if r["status"] >= 500], responses
            passed("no-uncaught-browser-errors-or-http-500s")
        except Exception as error:
            results.append({"check": "execution", "passed": False, "error": str(error)})
            capture("failure")
            raise
        finally:
            browser.close()


def main() -> None:
    require_isolation()
    if "--serve" in sys.argv:
        serve()
        return
    OUT.mkdir(parents=True, exist_ok=True)
    results, responses, page_errors = [], [], []
    try:
        with tempfile.TemporaryDirectory(prefix="northstar-figma-live-") as temporary:
            # Whitelist runtime infrastructure variables; no provider credentials,
            # production database, inherited .env or external deployment is reused.
            keep = [
                "PATH",
                "HOME",
                "SYSTEMROOT",
                "TEMP",
                "TMP",
                "LANG",
                "LD_LIBRARY_PATH",
                "PLAYWRIGHT_BROWSERS_PATH",
            ]
            env = {key: os.environ[key] for key in keep if key in os.environ}
            env.update(
                {
                    "PYTHONPATH": str(ROOT / "backend/src"),
                    "APP_ENV": "test",
                    "FIGMA_LIVE_REVIEW": "1",
                    "FIGMA_REVIEW_RUN": secrets.token_urlsafe(24),
                    "VITE_DEMO_MODE": "false",
                    "DATABASE_URL": f"sqlite+aiosqlite:///{temporary}/review.db",
                    "REDIS_URL": "redis://127.0.0.1:6399/15",
                    "APP_AUTO_CREATE_SCHEMA": "true",
                    "JWT_SECRET": secrets.token_urlsafe(48),
                    "SEED_ADMIN_EMAIL": "browser-review@example.com",
                    "SEED_ADMIN_PASSWORD": secrets.token_urlsafe(30),
                    "SEED_ADMIN_NAME": "Browser Review",
                    "SEED_TENANT_NAME": "Review Default",
                    "SEED_TENANT_PLAN": "legacy_custom_contract",
                    "SEED_DEMO_AGENT": "false",
                    "ALLOW_DETERMINISTIC_EMBEDDINGS": "true",
                    "RATE_LIMIT_FAIL_OPEN": "true",
                    "BACKGROUND_DISPATCH_ENABLED": "false",
                    "CRM_CREDENTIAL_ENCRYPTION_KEY": secrets.token_urlsafe(32),
                }
            )
            with (OUT / "server.log").open("w") as log:
                server = subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()), "--serve"],
                    cwd=temporary,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                try:
                    for _ in range(120):
                        if server.poll() is not None:
                            raise RuntimeError(
                                "Isolated API exited; inspect server.log"
                            )
                        try:
                            with urllib.request.urlopen(
                                BASE + "/__review_probe", timeout=1
                            ) as probe:
                                if (
                                    json.load(probe).get("run")
                                    != env["FIGMA_REVIEW_RUN"]
                                ):
                                    raise RuntimeError(
                                        "Port 4187 is occupied by another service; no test data was sent"
                                    )
                                break
                        except (urllib.error.URLError, TimeoutError):
                            time.sleep(0.5)
                    else:
                        raise RuntimeError("Isolated API startup timed out")
                    status, session = api(
                        "auth/login",
                        method="POST",
                        body={
                            "email": env["SEED_ADMIN_EMAIL"],
                            "password": env["SEED_ADMIN_PASSWORD"],
                        },
                    )
                    assert status == 200, session
                    token = session["accessToken"]
                    scopes = []
                    for suffix in ["A", "B"]:
                        status, workspace = api(
                            "workspaces",
                            method="POST",
                            token=token,
                            body={
                                "name": f"Figma Review {suffix}",
                                "slug": f"figma-review-{suffix.lower()}",
                            },
                        )
                        assert status == 201, workspace
                        status, agent = api(
                            "agents",
                            method="POST",
                            token=token,
                            workspace=workspace["id"],
                            body={
                                "name": f"Review Agent {suffix}",
                                "description": "Synthetic live-browser fixture",
                            },
                        )
                        assert status == 201, agent
                        scopes.append({"workspace": workspace, "agent": agent})
                    os.environ.update(env)
                    os.chdir(
                        temporary
                    )  # Do not load a repository-local .env in the seed helper.
                    sys.path.insert(0, str(ROOT / "backend/src"))
                    ids = asyncio.run(seed(scopes))
                    run_browser(
                        scopes,
                        ids,
                        env["SEED_ADMIN_EMAIL"],
                        env["SEED_ADMIN_PASSWORD"],
                        token,
                        results,
                        responses,
                        page_errors,
                    )
                finally:
                    server.terminate()
                    try:
                        server.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait(timeout=5)
    finally:
        (OUT / "summary.json").write_text(
            json.dumps(
                {
                    "mode": "non-demo production frontend + real FastAPI + disposable SQLite; not provider delivery",
                    "githubSha": os.environ.get("GITHUB_SHA"),
                    "results": results,
                    "pageErrors": page_errors,
                },
                indent=2,
            )
        )
        (OUT / "responses.json").write_text(json.dumps(responses, indent=2))


if __name__ == "__main__":
    main()
