"""Production frontend -> real FastAPI -> disposable SQLite browser regression.

Run only with APP_ENV=test FIGMA_LIVE_REVIEW=1, after a non-demo npm build.
This runner never accepts a deployment URL. It starts its own loopback server,
seeds synthetic records, and discards its database. It does not test PostgreSQL,
worker topology, real messaging delivery, billing or AI providers.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "review-results" / "live-browser"
BASE = "http://127.0.0.1:4187"


def require_isolation() -> None:
    if os.environ.get("APP_ENV") != "test" or os.environ.get("FIGMA_LIVE_REVIEW") != "1":
        raise RuntimeError("Explicit APP_ENV=test and FIGMA_LIVE_REVIEW=1 are required")
    if os.environ.get("VITE_DEMO_MODE", "false") != "false":
        raise RuntimeError("This test must not use a demo build")
    if not (ROOT / "frontend/dist/index.html").is_file():
        raise RuntimeError("Build the normal frontend before running the review")


def serve() -> None:
    """Add only static-file delivery after the application's actual API routes."""
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    import uvicorn
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


def api(path: str, *, method: str = "GET", body=None, token: str = "", workspace: str = ""):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if workspace:
        headers["X-Workspace-ID"] = workspace
    request = urllib.request.Request(
        BASE + "/api/v1/" + path, headers=headers, method=method,
        data=json.dumps(body).encode() if body is not None else None,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


async def seed(scopes: list[dict]) -> dict[str, str]:
    from datetime import UTC, datetime, timedelta
    from northstar_api.database import SessionFactory, close_database
    from northstar_api.models import Conversation, ConversationState, Message, MessageRole

    now = datetime.now(UTC)
    ids = {}
    entries = [(f"Resolved review {i}", "resolved", i, scopes[0]) for i in range(105)]
    entries.extend([
        ("Open review visitor", "open", 500, scopes[0]),
        ("Escalated review visitor", "escalated", 501, scopes[0]),
        ("Earlier month visitor", "open", 15 * 24 * 60, scopes[0]),
        ("Workspace B visitor", "open", 10, scopes[1]),
    ])
    async with SessionFactory() as session:
        for name, state, minutes, scope in entries:
            identifier = uuid4()
            ids[name] = str(identifier)
            tenant_id = UUID(scope["workspace"]["tenantId"])
            workspace_id = UUID(scope["workspace"]["id"])
            session.add(Conversation(
                id=identifier, tenant_id=tenant_id, workspace_id=workspace_id,
                agent_id=UUID(scope["agent"]["id"]), visitor_name=name,
                state=ConversationState(state), started_at=now - timedelta(minutes=minutes),
                updated_at=now - timedelta(minutes=minutes),
            ))
            session.add(Message(
                id=uuid4(), tenant_id=tenant_id, workspace_id=workspace_id,
                conversation_id=identifier, sequence=1, role=MessageRole.USER,
                content=f"Synthetic message from {name}", created_at=now - timedelta(minutes=minutes),
            ))
        await session.commit()
    await close_database()
    return ids


def run_browser(scopes: list[dict], ids: dict[str, str], email: str, password: str, token: str, results: list, responses: list, page_errors: list) -> None:
    from urllib.parse import urlparse
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1392, "height": 1000}, reduced_motion="reduce")
        # No API fulfilment/mocks. Local requests are sent unchanged to FastAPI.
        context.route("**/*", lambda route: route.continue_() if urlparse(route.request.url).hostname == "127.0.0.1" else route.abort())
        page = context.new_page()
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("response", lambda response: responses.append({"method": response.request.method, "path": urlparse(response.url).path, "query": urlparse(response.url).query, "status": response.status}) if "/api/" in response.url else None)

        def passed(name: str) -> None:
            results.append({"check": name, "passed": True})
            print(f"PASS {name}", flush=True)

        def choose_workspace(name: str) -> None:
            page.locator(".workspace-switcher__button").click()
            page.locator(".workspace-switcher__list button").filter(has_text=name).click()
            expect(page.locator(".workspace-switcher__button")).to_contain_text(name)

        try:
            page.goto(BASE + "/login")
            page.get_by_label("Work email", exact=True).fill(email)
            page.get_by_label("Password", exact=True).fill(password)
            with page.expect_response(lambda r: r.url.endswith("/auth/login") and r.request.method == "POST") as logged_in:
                page.get_by_role("button", name="Sign in", exact=True).click()
            assert logged_in.value.status == 200
            expect(page.locator(".saas-bot-shell")).to_be_visible(timeout=30000)
            passed("real-form-login-and-authenticated-shell")

            choose_workspace(scopes[0]["workspace"]["name"])
            metric = page.get_by_role("article", name="Conversations", exact=True).locator(".sb-metric__value")
            expect(metric).to_have_text("107", timeout=20000)
            expect(page.get_by_role("link", name="Open Review Agent A", exact=True)).to_be_visible()
            expect(page.get_by_role("link", name=re.compile("Open review visitor"))).to_be_visible()
            passed("live-workspace-dashboard-metrics-and-unresolved-queue")
            with page.expect_response(lambda r: "/analytics/summary?days=30" in r.url) as monthly:
                page.get_by_label("Chart period").select_option("30")
            assert monthly.value.status == 200
            expect(metric).to_have_text("108")
            passed("monthly-filter-roundtrip-and-database-derived-total")
            page.screenshot(path=str(OUT / "live-overview-desktop.png"), full_page=True)

            page.get_by_role("link", name=re.compile("Open review visitor")).click()
            identifier = ids["Open review visitor"]
            expect(page).to_have_url(re.compile(r"selected=" + identifier))
            expect(page.get_by_role("log", name="Conversation messages")).to_contain_text("Synthetic message from Open review visitor", timeout=20000)
            status, first_page = api("conversations?page=1&page_size=100", token=token, workspace=scopes[0]["workspace"]["id"])
            assert status == 200 and identifier not in {row["id"] for row in first_page["items"]}
            passed("off-page-dashboard-link-loads-correct-real-conversation")

            reply = "Synthetic browser reply saved by real FastAPI"
            page.get_by_placeholder("Reply as a teammate…").fill(reply)
            with page.expect_response(lambda r: f"/conversations/{identifier}/messages" in r.url and r.request.method == "POST") as sent:
                page.get_by_role("button", name="Send", exact=True).click()
            assert 200 <= sent.value.status < 300, sent.value.text()
            expect(page.get_by_role("log", name="Conversation messages")).to_contain_text(reply, timeout=15000)
            status, detail = api(f"conversations/{identifier}", token=token, workspace=scopes[0]["workspace"]["id"])
            assert status == 200 and any(message["content"] == reply for message in detail["messages"])
            passed("human-reply-ui-to-api-to-database-and-back")

            choose_workspace(scopes[1]["workspace"]["name"])
            expect(page.get_by_role("heading", name="Conversation is unavailable")).to_be_visible(timeout=15000)
            expect(page.get_by_role("log", name="Conversation messages")).to_have_count(0)
            status, _ = api(f"conversations/{identifier}", token=token, workspace=scopes[1]["workspace"]["id"])
            assert status == 404
            passed("workspace-switch-clears-old-thread-and-server-denies-cross-scope-detail")

            page.goto(BASE + "/")
            expect(page.get_by_role("link", name="Open Review Agent B", exact=True)).to_be_visible(timeout=15000)
            expect(page.get_by_role("link", name="Open Review Agent A", exact=True)).to_have_count(0)
            expect(page.get_by_role("article", name="Conversations", exact=True).locator(".sb-metric__value")).to_have_text("1")
            passed("second-workspace-dashboard-is-isolated")
            for width in [1392, 390]:
                page.set_viewport_size({"width": width, "height": 900})
                expect(page.locator(".sb-overview")).to_be_visible()
                page.wait_for_timeout(300)
                document_width = page.evaluate("document.documentElement.scrollWidth")
                if document_width > width:
                    overflow = page.evaluate("""() => [...document.querySelectorAll('*')].filter(e => e.getBoundingClientRect().right > innerWidth + 1).slice(0,80).map(e => ({tag:e.tagName, className:typeof e.className==='string'?e.className:'', left:e.getBoundingClientRect().left, right:e.getBoundingClientRect().right, width:e.getBoundingClientRect().width, position:getComputedStyle(e).position, overflowX:getComputedStyle(e).overflowX, parent:e.parentElement?.className || ''}))""")
                    (OUT / f"overview-overflow-{width}.json").write_text(json.dumps({"viewport":width,"documentWidth":document_width,"elements":overflow},indent=2))
                assert document_width <= width, f"Overview overflow at {width}: {document_width}"
                page.screenshot(path=str(OUT / f"live-overview-b-{width}.png"), full_page=True)
            passed("live-data-overview-desktop-and-mobile-no-overflow")
            page.set_viewport_size({"width": 1392, "height": 1000})

            page.get_by_role("link", name="Create agent", exact=True).click()
            dialog = page.get_by_role("dialog", name="Create an AI agent")
            expect(dialog.get_by_role("button", name="Continue", exact=True)).to_be_disabled()
            dialog.get_by_label("Agent name", exact=True).fill("Browser Created Review Agent")
            for _ in range(3):
                dialog.get_by_role("button", name="Continue", exact=True).click()
            with page.expect_response(lambda r: r.url.endswith("/agents") and r.request.method == "POST") as created_response:
                dialog.get_by_role("button", name="Create agent", exact=True).click()
            assert created_response.value.status == 201, created_response.value.text()
            created = created_response.value.json()
            expect(page).to_have_url(re.compile(f"/agents/{created['id']}/instructions"))
            status, stored = api("agents", token=token, workspace=scopes[1]["workspace"]["id"])
            assert status == 200 and any(agent["id"] == created["id"] and agent["name"] == "Browser Created Review Agent" for agent in stored)
            passed("existing-agent-wizard-creates-real-record-in-selected-workspace")
            page.goto(BASE + "/")
            expect(page.get_by_role("link", name="Open Browser Created Review Agent", exact=True)).to_be_visible(timeout=15000)
            passed("created-agent-survives-full-page-reload")

            assert api("conversations")[0] == 401
            assert api("conversations", token=token, workspace=str(uuid4()))[0] == 403
            passed("actual-http-rejects-anonymous-and-unknown-workspace")
            assert any(row["path"].endswith("/conversations") and "state=open" in row["query"] and row["status"] == 200 for row in responses)
            assert any(row["path"].endswith("/conversations") and "state=escalated" in row["query"] and row["status"] == 200 for row in responses)
            assert not [row for row in responses if row["status"] >= 500], "Backend server errors recorded in responses.json"
            assert not page_errors, page_errors
            passed("real-filtered-requests-no-browser-exceptions-or-server-errors")
        except Exception as error:
            results.append({"check": "execution", "passed": False, "error": str(error)})
            page.screenshot(path=str(OUT / "failure.png"), full_page=True)
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
            keep = ["PATH", "HOME", "SYSTEMROOT", "TEMP", "TMP", "LANG", "LD_LIBRARY_PATH", "PLAYWRIGHT_BROWSERS_PATH"]
            env = {key: os.environ[key] for key in keep if key in os.environ}
            env.update({
                "PYTHONPATH": str(ROOT / "backend/src"), "APP_ENV": "test", "FIGMA_LIVE_REVIEW": "1",
                "FIGMA_REVIEW_RUN": secrets.token_urlsafe(24),
                "VITE_DEMO_MODE": "false", "DATABASE_URL": f"sqlite+aiosqlite:///{temporary}/review.db",
                "REDIS_URL": "redis://127.0.0.1:6399/15", "APP_AUTO_CREATE_SCHEMA": "true",
                "JWT_SECRET": secrets.token_urlsafe(48), "SEED_ADMIN_EMAIL": "browser-review@example.com",
                "SEED_ADMIN_PASSWORD": secrets.token_urlsafe(30), "SEED_ADMIN_NAME": "Browser Review",
                "SEED_TENANT_NAME": "Review Default", "SEED_TENANT_PLAN": "legacy_custom_contract",
                "SEED_DEMO_AGENT": "false", "ALLOW_DETERMINISTIC_EMBEDDINGS": "true",
                "RATE_LIMIT_FAIL_OPEN": "true", "BACKGROUND_DISPATCH_ENABLED": "false",
                "CRM_CREDENTIAL_ENCRYPTION_KEY": secrets.token_urlsafe(32),
            })
            with (OUT / "server.log").open("w") as log:
                server = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve"], cwd=temporary, env=env, stdout=log, stderr=subprocess.STDOUT)
                try:
                    for _ in range(120):
                        if server.poll() is not None:
                            raise RuntimeError("Isolated API exited; inspect server.log")
                        try:
                            with urllib.request.urlopen(BASE + "/__review_probe", timeout=1) as probe:
                                if json.load(probe).get("run") != env["FIGMA_REVIEW_RUN"]:
                                    raise RuntimeError("Port 4187 is occupied by another service; no test data was sent")
                                break
                        except (urllib.error.URLError, TimeoutError):
                            time.sleep(0.5)
                    else:
                        raise RuntimeError("Isolated API startup timed out")
                    status, session = api("auth/login", method="POST", body={"email": env["SEED_ADMIN_EMAIL"], "password": env["SEED_ADMIN_PASSWORD"]})
                    assert status == 200, session
                    token = session["accessToken"]
                    scopes = []
                    for suffix in ["A", "B"]:
                        status, workspace = api("workspaces", method="POST", token=token, body={"name": f"Figma Review {suffix}", "slug": f"figma-review-{suffix.lower()}"})
                        assert status == 201, workspace
                        status, agent = api("agents", method="POST", token=token, workspace=workspace["id"], body={"name": f"Review Agent {suffix}", "description": "Synthetic live-browser fixture"})
                        assert status == 201, agent
                        scopes.append({"workspace": workspace, "agent": agent})
                    os.environ.update(env)
                    os.chdir(temporary)  # Do not load a repository-local .env in the seed helper.
                    sys.path.insert(0, str(ROOT / "backend/src"))
                    ids = asyncio.run(seed(scopes))
                    run_browser(scopes, ids, env["SEED_ADMIN_EMAIL"], env["SEED_ADMIN_PASSWORD"], token, results, responses, page_errors)
                finally:
                    server.terminate()
                    try:
                        server.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait(timeout=5)
    finally:
        (OUT / "summary.json").write_text(json.dumps({"mode": "non-demo production frontend + real FastAPI + disposable SQLite; not provider delivery", "githubSha": os.environ.get("GITHUB_SHA"), "results": results, "pageErrors": page_errors}, indent=2))
        (OUT / "responses.json").write_text(json.dumps(responses, indent=2))


if __name__ == "__main__":
    main()
