"""
Drive the CP6 flow in a real browser against the running stack (scripts/dev.sh)
and save screenshots: imports -> plan -> PO drafts -> edit -> approve -> captured send.

    .venv/bin/python scripts/ui_walkthrough.py [--out docs/screenshots/cp6]

Expects a freshly seeded demo workspace (python -m clawbot.devtools.seed_demo, without --import).
"""

from __future__ import annotations

import argparse
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import Page, expect, sync_playwright

UI = "http://127.0.0.1:5173"
ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "var" / "demo"
TZ = ZoneInfo("America/New_York")


def shot(page: Page, out: Path, name: str) -> None:
    page.wait_for_timeout(300)
    page.screenshot(path=str(out / f"{name}.png"), full_page=True)
    print("saved", name)


def sign_in(page: Page, user: str) -> None:
    page.goto(f"{UI}/ops/setup")
    page.get_by_placeholder("owner@yourstore.com").fill(user)
    page.get_by_role("button", name="Continue").click()
    page.get_by_role("button", name=re.compile("^(Open|Current — open)$")).first.click()
    page.goto(f"{UI}/ops/setup")
    page.get_by_role("button", name=re.compile("Use this location|Selected")).first.click()


def import_file(page: Page, kind_label: str, path: Path, settings: dict[str, str]) -> None:
    page.goto(f"{UI}/ops/imports")
    page.get_by_label("What is it?").select_option(label=kind_label)
    page.get_by_label("CSV or XLSX").set_input_files(str(path))
    page.get_by_role("button", name="Upload").click()
    expect(page.get_by_text(f"Review: {path.name}")).to_be_visible(timeout=15000)
    for label, value in settings.items():
        field = page.get_by_label(label)
        if field.evaluate("e => e.tagName") == "SELECT":
            field.select_option(value)
        else:
            field.fill(value)
    page.get_by_role("button", name="Save and re-check").click()
    confirm = page.get_by_role("button", name="Confirm and apply")
    expect(confirm).to_be_enabled(timeout=15000)
    return confirm


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "docs" / "screenshots" / "cp6"))
    out = Path(parser.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    today = datetime.now(TZ).date()
    count_at = (datetime.now(TZ) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    now = datetime.now(TZ).strftime("%Y-%m-%dT%H:%M")

    with sync_playwright() as pw:
        # PLAYWRIGHT_CHANNEL=chrome uses the installed Google Chrome instead of a downloaded build.
        browser = pw.chromium.launch(channel=os.getenv("PLAYWRIGHT_CHANNEL") or None)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        sign_in(page, "owner@pawsandco.example")
        shot(page, out, "01_workspace")
        page.goto(f"{UI}/ops/orders")
        expect(page.get_by_text("No purchase orders yet")).to_be_visible(timeout=15000)
        shot(page, out, "01b_orders_empty")

        # 1. Imports through the review screen (declared meaning is restated by the person).
        confirm = import_file(page, "Sales history", SAMPLES / "sales_last_28_days.csv", {
            "Export covers sales from (date)": (today - timedelta(days=28)).isoformat(),
            "Export covers sales until (date)": (today - timedelta(days=1)).isoformat(),
        })
        shot(page, out, "02_import_review_sales")
        confirm.click()
        expect(page.get_by_text("Applied").first).to_be_visible(timeout=30000)
        import_file(page, "Stock count", SAMPLES / "stock_count.csv", {"This was true at": count_at}).click()
        import_file(page, "Open (not yet received) orders", SAMPLES / "open_orders.csv", {
            "This was true at": now, "Quantities are in": "base",
            "This report lists every open order for": "suppliers_in_file",
        }).click()
        page.wait_for_timeout(1500)
        page.reload()
        expect(page.get_by_text("Applying…")).to_have_count(0, timeout=30000)
        shot(page, out, "03_imports_applied")

        # 2. Plan.
        page.goto(f"{UI}/ops/today")
        page.get_by_role("button", name=re.compile("Compute plan|Recompute plan")).click()
        expect(page.get_by_text("Recommendations")).to_be_visible(timeout=30000)
        shot(page, out, "04_plan")
        row = page.locator("tr", has_text="LITTER-20").first
        row.get_by_role("button", name="Why?").click()
        shot(page, out, "05_plan_why_litter")
        row.get_by_role("button", name="Hide").click()
        page.locator("tr", has_text="CATFOOD-3").first.get_by_role("button", name="Why?").click()
        shot(page, out, "06_plan_on_hold_catfood")

        # 3. Drafts, one per supplier.
        page.get_by_role("button", name=re.compile("Create PO drafts")).click()
        expect(page.get_by_text("PO-00001")).to_be_visible(timeout=15000)
        shot(page, out, "07_po_list_drafts")
        page.locator("tr", has_text="Phillips").get_by_role("link").click()
        expect(page.get_by_text("Lines")).to_be_visible()
        shot(page, out, "08_po_draft")
        page.get_by_role("button", name="Basis").first.click()
        shot(page, out, "08b_po_line_basis")
        page.get_by_role("button", name="Hide basis").click()

        # 4. Edit a quantity -> new revision.
        page.get_by_label("Quantity for line 1").fill("8")
        page.get_by_role("button", name="Save quantities").click()
        expect(page.get_by_text(re.compile("Revision 2"))).to_be_visible(timeout=15000)
        shot(page, out, "09_po_edited_rev2")

        # 5. Submit and approve (owner), then the worker captures the test send.
        page.get_by_role("button", name="Submit for approval").click()
        approve = page.get_by_role("button", name=re.compile("Approve revision 2"))
        expect(approve).to_be_enabled(timeout=15000)
        shot(page, out, "10_po_awaiting_approval")
        approve.click()
        expect(page.get_by_text("Test sent (captured)").first).to_be_visible(timeout=30000)
        shot(page, out, "11_po_test_sent")
        page.reload()
        expect(page.get_by_text("Test sent (captured)").first).to_be_visible(timeout=15000)
        shot(page, out, "12_po_after_refresh")

        # 6. A manager can submit but cannot approve (button disabled; server answers 403).
        page.goto(f"{UI}/ops/orders")
        coastal = page.locator("tr", has_text="Coastal").get_by_role("link")
        coastal.click()
        page.get_by_role("button", name="Submit for approval").click()
        expect(page.get_by_role("button", name=re.compile("Approve revision"))).to_be_visible(timeout=15000)
        po_url = page.url
        sign_in(page, "manager@pawsandco.example")
        page.goto(po_url)
        expect(page.get_by_text("Waiting for the owner to approve.")).to_be_visible(timeout=15000)
        status = page.evaluate("""async () => {
            const s = JSON.parse(localStorage.getItem('tabula.session.v1'));
            const id = location.pathname.split('/').pop();
            const po = await (await fetch(`/v1/purchase-orders/${id}`, {headers: {'X-Dev-User': s.user, 'X-Tenant-Id': s.tenantId}})).json();
            const r = await fetch(`/v1/purchase-orders/${id}/approve`, {method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-Dev-User': s.user, 'X-Tenant-Id': s.tenantId},
                body: JSON.stringify({revision: po.revision, digest: po.digest})});
            return r.status;
        }""")
        print("manager approve via API ->", status)
        assert status == 403
        shot(page, out, "13_po_manager_cannot_approve")
        browser.close()


if __name__ == "__main__":
    main()
