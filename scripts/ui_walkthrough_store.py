"""
Owner path in a real browser against the running stack (scripts/dev.sh), screenshots per step:
sample store → what needs attention → order analysis → order kept in test mode → an export order whose number
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

from _ui_helpers import import_file

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

        # 1. A new account opens the sample store from "Your stores" (it is marked as a sample everywhere).
        page.goto(f"{UI}/signin")
        page.get_by_role("button", name=re.compile("Demo sign-in")).click()
        page.locator("form").last.locator("input").fill(owner)
        page.get_by_role("button", name="Continue").click()
        expect(page.get_by_role("button", name="Create a sample store")).to_be_visible(timeout=15000)
        shot(page, out, "01_stores_sample_button")
        page.get_by_role("button", name="Create a sample store").click()  # builds it, then opens it
        page.wait_for_url(re.compile(r"/app$"), timeout=180000)

        # 2. Home: what needs the owner, before anything is computed.
        expect(page.get_by_text("Runs out soonest")).to_be_visible(timeout=15000)
        shot(page, out, "02_home_today_before_analysis")
        page.goto(f"{UI}/app/orders")
        page.get_by_role("button", name=re.compile("Run order analysis|Run again")).click()
        expect(page.get_by_text("Suggested orders")).to_be_visible(timeout=30000)
        shot(page, out, "03_order_suggestions")

        # 3. Drafts → the Phillips order approved and kept in test mode (not emailed).
        page.get_by_role("button", name=re.compile("Create .* order draft")).click()
        page.wait_for_url(re.compile("/app/orders/list"), timeout=15000)
        page.get_by_role("link", name=re.compile("Phillips")).click()
        page.get_by_role("button", name="Submit for approval").click()
        approve = page.get_by_role("button", name=re.compile("Approve version"))
        expect(approve).to_be_enabled(timeout=15000)
        approve.click()
        expect(page.get_by_text(re.compile(r"Sent \(test mode\)")).first).to_be_visible(timeout=30000)
        phillips_url = page.url
        number = page.locator("h1").inner_text().split()[-1]  # e.g. PO-00001

        # 4. The store's own open-orders file lists that order as "PO00001" — only the number nearly matches.
        near = number.replace("-", "")
        path = csv_file([["Supplier", "PO #", "SKU", "Qty Remaining", "Confirmed"],
                         ["Phillips Pet Supply", near, "LITTER-20", "84", "no"]], "open_orders_from_pos.csv")
        import_file(page, "open_orders", Path(path), {"Quantities are counted in": "base", "This file lists": "none"}, now=True)
        page.goto(f"{UI}/app/orders")
        expect(page.get_by_text("Is this export order one of your Tabula orders?")).to_be_visible(timeout=15000)
        shot(page, out, "05_possible_duplicate_order")
        page.get_by_role("button", name=f"Same order as {number}").click()
        page.wait_for_timeout(1500)
        page.get_by_role("button", name=re.compile("Run again|Run order analysis")).click()
        page.wait_for_timeout(1500)
        litter = page.locator("tr", has_text="LITTER-20").first
        if litter.count():
            litter.get_by_role("button", name="Why?").click()
        else:
            page.locator("li", has_text="LITTER-20").first.get_by_role("button", name="Details").click()
        shot(page, out, "06_after_same_order_decision")

        # 5. A sales file: the preview suggests the file's own date range; the owner confirms it.
        now = datetime.now(TZ)
        early = now - timedelta(minutes=30)
        path = csv_file([["Date", "Transaction ID", "SKU", "Qty"],
                         [early.isoformat(timespec="seconds"), "T-today-1", "TREATS-6", "2"],
                         [(early + timedelta(minutes=5)).isoformat(timespec="seconds"), "T-today-2", "DOGFOOD-30", "1"]],
                        "sales_today.csv")
        import_file(page, "sales", Path(path), {}, suggested_dates=True, shot_as=lambda: shot(page, out, "07_import_sales_suggested_dates"))

        # 6. Square (mock): connect and link the store — its stock now belongs to Square (read-only).
        page.goto(f"{UI}/app/data/square")
        page.get_by_role("button", name=re.compile("Connect Square")).click()
        expect(page.get_by_text("Mock Pets")).to_be_visible(timeout=15000)
        page.get_by_label("Square location").select_option(index=1)
        page.get_by_label("Tabula location").select_option(index=1)
        page.get_by_role("button", name="Link").click()
        expect(page.get_by_text("Sales source:")).to_be_visible(timeout=15000)
        shot(page, out, "08_connections_square_mock_linked")

        # 7. A delivery at a Square-owned store: Tabula cannot write Square stock — evidence, then a sign-off.
        page.goto(phillips_url.replace("/app/orders/", "/app/receiving/"))
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

        page.goto(f"{UI}/app")
        expect(page.get_by_text("Runs out soonest")).to_be_visible(timeout=15000)
        shot(page, out, "12_home_end")
        status, _ = call(page, "GET", "/attention?location_id=" + page.evaluate("JSON.parse(localStorage.getItem('tabula.session.v1')).locationId"))
        print("attention endpoint ->", status)
        # Disconnect the demo Square account: one Square account belongs to one store, so the next run can connect it.
        _, accounts = call(page, "GET", "/connectors")
        for account in accounts:
            print("disconnect demo Square ->", call(page, "DELETE", f"/connectors/{account['id']}")[0])
        browser.close()


if __name__ == "__main__":
    main()
