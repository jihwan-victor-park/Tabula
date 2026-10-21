"""
Owner path in a real browser against the running stack (scripts/dev.sh), screenshots per step:
demo store → what needs attention → plan → order sent (capture) → an export order whose number
nearly matches → the person decides → sales file with suggested dates → Square (mock) connection →
receipt at a Square-owned store → POS evidence → sign-off.

    PLAYWRIGHT_CHANNEL=chrome .venv/bin/python scripts/ui_walkthrough_store.py [--out docs/screenshots/store-readiness]
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import Page, expect, sync_playwright

UI = "http://127.0.0.1:5173"
ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("America/New_York")


def shot(page: Page, out: Path, name: str) -> None:
    page.wait_for_timeout(400)
    page.screenshot(path=str(out / f"{name}.png"), full_page=True)
    print("saved", name)


def call(page: Page, method: str, path: str, body=None):
    return page.evaluate("""async ([method, path, body]) => {
        const s = JSON.parse(localStorage.getItem('tabula.session.v1'));
        const r = await fetch('/v1' + path, {method, headers: {'Content-Type': 'application/json', 'X-Dev-User': s.user,
            'X-Tenant-Id': s.tenantId}, body: body ? JSON.stringify(body) : undefined});
        return [r.status, await r.json().catch(() => null)];
    }""", [method, path, body])


def csv_file(rows: list[list[str]], name: str) -> str:
    path = Path(tempfile.mkdtemp()) / name
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    path.write_text(buf.getvalue())
    return str(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "docs" / "screenshots" / "store-readiness"))
    out = Path(parser.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    owner = f"owner+{uuid.uuid4().hex[:6]}@corner.example"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=os.getenv("PLAYWRIGHT_CHANNEL") or None)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        # 1. A new owner creates the demo store from the Workspace screen (development only).
        page.goto(f"{UI}/ops/setup")
        page.get_by_placeholder("owner@yourstore.com").fill(owner)
        page.get_by_role("button", name="Continue").click()
        expect(page.get_by_role("button", name="Create a demo store")).to_be_visible(timeout=15000)
        shot(page, out, "01_workspace_demo_button")
        page.get_by_role("button", name="Create a demo store").click()
        expect(page.get_by_text("Role: owner")).to_be_visible(timeout=180000)
        page.get_by_role("button", name="Open").first.click()
        page.goto(f"{UI}/ops/setup")
        page.get_by_role("button", name=re.compile("Use this location")).first.click()

        # 2. Today: what needs the owner, before anything is computed.
        page.goto(f"{UI}/ops/today")
        expect(page.get_by_text("Needs your attention")).to_be_visible(timeout=15000)
        shot(page, out, "02_today_attention_before_plan")
        page.get_by_role("button", name=re.compile("Compute plan|Recompute plan")).click()
        expect(page.get_by_text("Recommendations")).to_be_visible(timeout=30000)
        shot(page, out, "03_today_plan_and_attention")

        # 3. Drafts → the Phillips order approved and captured (test send).
        page.get_by_role("button", name=re.compile("Create PO drafts")).click()
        page.wait_for_url(re.compile("/ops/orders"), timeout=15000)
        page.goto(f"{UI}/ops/orders")
        page.locator("tr", has_text="Phillips").get_by_role("link").click()
        page.get_by_role("button", name="Submit for approval").click()
        approve = page.get_by_role("button", name=re.compile("Approve revision"))
        expect(approve).to_be_enabled(timeout=15000)
        approve.click()
        try:
            expect(page.get_by_text(re.compile(r"Sent \(test capture\)")).first).to_be_visible(timeout=30000)
        except AssertionError:
            shot(page, out, "debug_approve")
            raise
        phillips_url = page.url
        number = page.locator("h1").inner_text().split()[-1]  # e.g. PO-00002

        # 4. The store's own open-orders file lists that order as "PO00002" — only the number nearly matches.
        near = number.replace("-", "")
        path = csv_file([["Supplier", "PO #", "SKU", "Qty Remaining", "Confirmed"],
                         ["Phillips Pet Supply", near, "LITTER-20", "84", "no"]], "open_orders_from_pos.csv")
        page.goto(f"{UI}/ops/imports")
        page.get_by_label("What is it?").select_option(label="Open (not yet received) orders")
        page.get_by_label("CSV or XLSX").set_input_files(path)
        page.get_by_role("button", name="Upload").click()
        expect(page.get_by_text("Review: open_orders_from_pos.csv")).to_be_visible(timeout=15000)
        page.get_by_role("button", name="Now").click()
        page.get_by_label("Quantities are in").select_option("base")
        page.get_by_label("This report lists every open order for").select_option("none")
        page.get_by_role("button", name="Save and re-check").click()
        confirm = page.get_by_role("button", name="Confirm and apply")
        expect(confirm).to_be_enabled(timeout=15000)
        shot(page, out, "04_import_open_orders_with_now")
        confirm.click()
        page.wait_for_timeout(2500)
        page.goto(f"{UI}/ops/today")
        expect(page.get_by_text("Is this export order one of your Tabula orders?")).to_be_visible(timeout=15000)
        shot(page, out, "05_today_possible_duplicate_order")
        page.get_by_role("button", name=f"Same order as {number}").click()
        page.wait_for_timeout(1500)
        page.get_by_role("button", name=re.compile("Recompute plan")).click()
        page.wait_for_timeout(1500)
        page.locator("tr", has_text="LITTER-20").first.get_by_role("button", name="Why?").click()
        shot(page, out, "06_today_after_same_order_decision")

        # 5. A sales file: the preview suggests the file's own date range; the owner confirms it.
        now = datetime.now(TZ)
        early = now - timedelta(minutes=30)
        path = csv_file([["Date", "Transaction ID", "SKU", "Qty"],
                         [early.isoformat(timespec="seconds"), "T-today-1", "TREATS-6", "2"],
                         [(early + timedelta(minutes=5)).isoformat(timespec="seconds"), "T-today-2", "DOGFOOD-30", "1"]],
                        "sales_today.csv")
        page.goto(f"{UI}/ops/imports")
        page.get_by_label("What is it?").select_option(label="Sales history")
        page.get_by_label("CSV or XLSX").set_input_files(path)
        page.get_by_role("button", name="Upload").click()
        expect(page.get_by_text("Use these dates")).to_be_visible(timeout=15000)
        shot(page, out, "07_import_sales_suggested_dates")
        page.get_by_text("Use these dates").click()
        page.get_by_role("button", name="Save and re-check").click()
        expect(page.get_by_role("button", name="Confirm and apply")).to_be_enabled(timeout=15000)
        page.get_by_role("button", name="Confirm and apply").click()

        # 6. Square (mock): connect and link the store — its stock now belongs to Square (read-only).
        page.goto(f"{UI}/ops/connections")
        page.get_by_role("button", name=re.compile("Connect Square")).click()
        expect(page.get_by_text("Mock Pets")).to_be_visible(timeout=15000)
        page.get_by_label("Square location").select_option(index=1)
        page.get_by_label("Tabula location").select_option(index=1)
        page.get_by_role("button", name="Link").click()
        expect(page.get_by_text("Sales source:")).to_be_visible(timeout=15000)
        shot(page, out, "08_connections_square_mock_linked")

        # 7. A delivery at a Square-owned store: Tabula cannot write Square stock — evidence, then a sign-off.
        page.goto(phillips_url.replace("/ops/orders/", "/ops/receiving/"))
        page.get_by_label("Arrived for line 1").fill("2")
        page.get_by_role("button", name="Record delivery").click()
        expect(page.get_by_text("not in the POS yet")).to_be_visible(timeout=15000)
        shot(page, out, "09_receiving_pending_pos")
        page.get_by_role("button", name="I entered it in the POS").click()
        page.get_by_text("Compare with the POS").click()
        expect(page.get_by_text(re.compile("No POS reading"))).to_be_visible(timeout=15000)
        shot(page, out, "10_pos_evidence_no_reading")
        page.get_by_role("button", name="POS is right").click()
        expect(page.get_by_text(re.compile("Say what you checked"))).to_be_visible(timeout=15000)
        page.get_by_placeholder(re.compile("What you checked")).fill("Checked Square: received 24 units at 2:10pm, stock 60")
        page.get_by_role("button", name="POS is right").click()
        expect(page.get_by_text("reconciled with the POS")).to_be_visible(timeout=15000)
        shot(page, out, "11_pos_reconciled")

        page.goto(f"{UI}/ops/today")
        expect(page.get_by_text("Needs your attention")).to_be_visible(timeout=15000)
        shot(page, out, "12_today_attention_end")
        status, _ = call(page, "GET", "/attention?location_id=" + page.evaluate("JSON.parse(localStorage.getItem('tabula.session.v1')).locationId"))
        print("attention endpoint ->", status)
        browser.close()


if __name__ == "__main__":
    main()
