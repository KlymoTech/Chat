"""Exported Education designs: non-demo UI against the real disposable FastAPI.

Reuses the existing isolated runner (loopback only, random test credentials,
throwaway database, no inherited provider credentials). No API response is mocked.
This is not a production deployment, messaging-delivery or AI-provider test.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
import os

import leads_browser_review as runtime

OUT = runtime.ROOT / "review-results" / "education-browser"


async def seed(scopes: list[dict]) -> dict:
    status, session = runtime.api("auth/login", method="POST", body={
        "email": os.environ["SEED_ADMIN_EMAIL"], "password": os.environ["SEED_ADMIN_PASSWORD"],
    })
    assert status == 200, session
    token, workspace = session["accessToken"], scopes[0]["workspace"]["id"]

    def create(path: str, body: dict) -> dict:
        code, record = runtime.api(path, method="POST", token=token, workspace=workspace, body=body)
        assert code == 201, (path, code, record)
        return record

    agent = create("agents", {"name": "CMA AI", "purpose": "education", "deploymentChannel": "website", "description": "Synthetic export review assistant"})
    today = datetime.now(UTC).date()
    courses, batches, students = [], [], []
    for index, (code, name, description) in enumerate([
        ("CMA-P1", "CMA Part 1", "Financial planning and accounting"),
        ("CS-CORE", "Computer Science", "AI & data science"),
        ("MBA-01", "MBA", "Corporate finance"),
    ]):
        course = create("education/courses", {"code": code, "name": name, "description": description})
        courses.append(course)
        batch = create("education/batches", {"courseId": course["id"], "code": f"{code}-A", "name": f"{name} · Morning Batch", "description": "Synthetic morning cohort", "startsOn": str(today - timedelta(days=30)), "endsOn": str(today + timedelta(days=120))})
        batches.append(batch)
        student = create("education/students", {"studentNumber": f"ED-{index+1}", "name": ["Asha Verma", "Ravi Shah", "Priya S"][index], "email": f"student-{index+1}@example.com"})
        students.append(student)
        enrollment = create("education/enrollments", {"studentId": student["id"], "courseId": course["id"], "batchId": batch["id"], "agentId": agent["id"], "startsOn": str(today - timedelta(days=1)), "endsOn": str(today + timedelta(days=60))})
        if index == 0:
            assert runtime.api(f"education/enrollments/{enrollment['id']}", method="PATCH", token=token, workspace=workspace, body={"status": "active"})[0] == 200
    # The real service requires an active enrollment before activating its agent.
    assert runtime.api(f"agents/{agent['id']}", method="PATCH", token=token, workspace=workspace, body={"status": "active"})[0] == 200
    return {"courses": courses, "batches": batches, "students": students, "agent": agent}


def run_browser(scopes, ids, email, password, token, results, responses, page_errors) -> None:
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1100}, reduced_motion="reduce")
        context.route("**/*", lambda route: route.continue_() if urlparse(route.request.url).hostname == "127.0.0.1" else route.abort())
        page = context.new_page()
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on("response", lambda r: responses.append({"method": r.request.method, "path": urlparse(r.url).path, "status": r.status}) if "/api/" in r.url else None)

        def passed(name):
            results.append({"check": name, "passed": True})
            print("PASS", name, flush=True)

        def capture(name):
            page.evaluate("document.fonts.ready")
            page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)

        def workspace(name):
            page.locator(".workspace-switcher__button").click()
            page.locator(".workspace-switcher__list button").filter(has_text=name).click()
            expect(page.locator(".workspace-switcher__button")).to_contain_text(name)

        try:
            page.goto(runtime.BASE + "/login")
            page.get_by_label("Work email", exact=True).fill(email)
            page.get_by_label("Password", exact=True).fill(password)
            page.get_by_role("button", name="Sign in", exact=True).click()
            expect(page.locator(".saas-bot-shell")).to_be_visible(timeout=30000)
            workspace(scopes[0]["workspace"]["name"])
            page.goto(runtime.BASE + "/education")
            expect(page.get_by_role("heading", name="Education Hub", exact=True)).to_be_visible()
            expect(page.locator(".ed-metric > strong")).to_have_text(["3", "1", "3", "1"])
            expect(page.get_by_role("link", name="View course CMA Part 1", exact=True)).to_be_visible()
            passed("real-login-workspace-data-and-date-checked-education-summary")
            capture("education-overview-desktop")
            for width in [1024, 768, 390, 360]:
                page.set_viewport_size({"width": width, "height": 950})
                page.wait_for_timeout(300)
                actual = page.evaluate("document.documentElement.scrollWidth")
                assert actual <= width, f"Overview overflow {actual} > {width}"
                capture(f"education-overview-{width}")
            passed("education-overview-responsive-at-five-widths")
            page.set_viewport_size({"width": 1440, "height": 1100})
            page.get_by_label("Academy chart period").select_option("30")
            expect(page.get_by_role("img", name="Enrollments created in the last 30 days")).to_be_visible()
            passed("education-chart-period-control")
            page.get_by_role("link", name="View course CMA Part 1", exact=True).click()
            expect(page.locator(".ed-record-detail h2")).to_have_text("CMA Part 1")
            expect(page.locator(".ed-detail-table").last).to_contain_text("Asha Verma")
            capture("education-course-detail")
            passed("course-detail-shows-real-batches-and-student-roster")
            page.get_by_role("link", name="CMA Part 1 · Morning Batch", exact=True).click()
            expect(page.locator(".ed-record-detail h2")).to_have_text("CMA Part 1 · Morning Batch")
            expect(page.locator(".ed-detail-table")).to_contain_text("Asha Verma")
            capture("education-batch-detail")
            passed("batch-detail-deep-link-and-roster")
            page.get_by_role("button", name="Edit batch", exact=True).click()
            editor = page.get_by_role("region", name="Edit batch", exact=True)
            expect(editor).to_be_visible()
            expect(editor.get_by_label("Course", exact=True)).to_be_disabled()
            editor.get_by_label("Batch name", exact=True).fill("CMA Part 1 Evening Cohort")
            expect(page.get_by_label("Cohort Live Preview")).to_contain_text("CMA Part 1 Evening Cohort")
            capture("education-edit-batch")
            editor.get_by_role("button", name="Save changes", exact=True).click()
            expect(editor).not_to_be_visible()
            expect(page.locator(".ed-record-detail h2")).to_have_text("CMA Part 1 Evening Cohort")
            assert runtime.api(f"education/batches/{ids['batches'][0]['id']}", token=token, workspace=scopes[0]['workspace']['id'])[1]['name'] == "CMA Part 1 Evening Cohort"
            passed("full-page-batch-edit-persists-through-real-api")
            page.goto(runtime.BASE + "/education/batches?create=1&source=hub&courseId=" + ids['courses'][0]['id'])
            editor = page.get_by_role("region", name="Create batch", exact=True)
            expect(editor.get_by_label("Course", exact=True)).to_have_value(ids['courses'][0]['id'])
            editor.get_by_label("Batch code", exact=True).fill("CMA-EXPORT-B")
            editor.get_by_label("Batch name", exact=True).fill("Export Review Cohort")
            editor.get_by_label("Description", exact=True).fill("Native full-page editor using existing API fields")
            editor.get_by_label("Start date", exact=True).fill("2026-10-01")
            editor.get_by_label("End date", exact=True).fill("2027-03-31")
            capture("education-create-batch")
            page.set_viewport_size({"width": 390, "height": 950})
            page.wait_for_timeout(300)
            assert page.evaluate("document.documentElement.scrollWidth") <= 390
            capture("education-create-batch-mobile")
            page.set_viewport_size({"width": 1440, "height": 1100})
            editor.get_by_role("button", name="Create batch", exact=True).click()
            expect(editor).not_to_be_visible()
            expect(page.get_by_role("link", name="Export Review Cohort", exact=True)).to_be_visible()
            assert "source=hub" in page.url and "create=" not in page.url
            capture("education-batch-catalog")
            passed("create-batch-deep-link-preview-responsive-and-api-persistence")
            page.goto(runtime.BASE + "/education/courses?create=1&source=hub")
            modal = page.get_by_role("dialog", name="Create course", exact=True)
            expect(modal).to_be_visible()
            modal.get_by_label("Course code", exact=True).fill("EXPORT-01")
            modal.get_by_label("Course name", exact=True).fill("Export Review Course")
            capture("education-create-course")
            modal.get_by_role("button", name="Create course", exact=True).click()
            expect(modal).not_to_be_visible()
            expect(page.get_by_role("link", name="Export Review Course", exact=True)).to_be_visible()
            assert "source=hub" in page.url and "create=" not in page.url
            capture("education-course-catalog")
            page.get_by_label("Search courses", exact=True).fill("EXPORT-01")
            expect(page.locator(".course-table tbody tr")).to_have_count(1)
            passed("course-create-deep-link-persists-and-searches-live-records")
            page.goto(runtime.BASE + "/education/enrollments?create=1&source=hub")
            modal = page.get_by_role("dialog", name="Choose student", exact=True)
            expect(modal).to_be_visible()
            expect(modal.get_by_role("button", name="Continue", exact=True)).to_be_disabled()
            modal.get_by_role("button", name="Cancel", exact=True).click()
            expect(modal).not_to_be_visible()
            assert "source=hub" in page.url and "create=" not in page.url
            passed("create-enrollment-opens-existing-student-picker-and-preserves-query")
            page.goto(runtime.BASE + "/education/students?create=1&source=hub")
            modal = page.get_by_role("dialog", name="Add student", exact=True)
            expect(modal).to_be_visible()
            modal.get_by_role("button", name="Cancel", exact=True).click()
            expect(modal).not_to_be_visible()
            assert "source=hub" in page.url and "create=" not in page.url
            passed("add-student-opens-existing-create-workflow")
            page.goto(runtime.BASE + "/education/courses")
            workspace(scopes[1]["workspace"]["name"])
            expect(page.locator(".course-table tbody tr")).to_have_count(0)
            assert page.get_by_text("Export Review Course", exact=True).count() == 0
            page.goto(runtime.BASE + "/education")
            expect(page.locator(".ed-metric > strong")).to_have_text(["0", "0", "0", "0"])
            assert page.get_by_role("link", name="View course CMA Part 1", exact=True).count() == 0
            passed("workspace-switch-clears-catalog-and-education-summary")
            for endpoint in ['education/courses', 'education/batches', 'education/students', 'education/enrollments']:
                assert runtime.api(endpoint, token=token, workspace=scopes[1]['workspace']['id'])[1] == []
            assert runtime.api(f"education/courses/{ids['courses'][0]['id']}", token=token, workspace=scopes[1]['workspace']['id'])[0] == 404
            passed("backend-workspace-isolation-and-cross-workspace-detail-denial")
            assert not page_errors, page_errors
            assert not [r for r in responses if r['status'] >= 500], responses
            passed("no-uncaught-browser-errors-or-http-500s")
        except Exception as error:
            results.append({"check": "execution", "passed": False, "error": str(error)})
            capture("failure")
            raise
        finally:
            browser.close()


if __name__ == '__main__':
    # Reuse only the isolation/launch/report harness; application APIs are untouched.
    runtime.OUT = OUT
    runtime.seed = seed
    runtime.run_browser = run_browser
    runtime.main()
