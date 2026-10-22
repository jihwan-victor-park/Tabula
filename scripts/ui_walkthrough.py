"""
Drive the order flow (CP6–CP8) in a real browser against the running stack (scripts/dev.sh)
and save screenshots: imports -> plan -> PO drafts -> edit -> approve -> captured send.

    .venv/bin/python scripts/ui_walkthrough.py [--out docs/screenshots/cp7]

Seeds its own demo store (python -m clawbot.devtools.seed_demo, without --import) for a fresh owner.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import Page, expect, sync_playwright

from _ui_helpers import demo_sign_in, import_file, seed_demo_store
from playwright.sync_api import TimeoutError as PlaywrightTimeout

UI = "http://127.0.0.1:5173"
ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "var" / "demo"
TZ = ZoneInfo("America/New_York")
SENT_LABEL = re.compile(r"Sent \(test mode\)")


def shot(page: Page, out: Path, name: str) -> None:
    page.wait_for_timeout(300)
    page.screenshot(path=str(out / f"{name}.png"), full_page=True)
    print("saved", name)


import uuid

OWNER = f"owner+{uuid.uuid4().hex[:6]}@pawsandco.example"
MANAGER = "manager@pawsandco.example"
TENANT: dict[str, str] = {}


def sign_in(page: Page, user: str) -> None:
    demo_sign_in(page, user, tenant_id=TENANT["id"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "docs" / "screenshots" / "cp7"))
    out = Path(parser.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    today = datetime.now(TZ).date()
    count_at = (datetime.now(TZ) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    now = datetime.now(TZ).strftime("%Y-%m-%dT%H:%M")

    TENANT["id"] = seed_demo_store(OWNER)
    with sync_playwright() as pw:
        # PLAYWRIGHT_CHANNEL=chrome uses the installed Google Chrome instead of a downloaded build.
        browser = pw.chromium.launch(channel=os.getenv("PLAYWRIGHT_CHANNEL") or None)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        sign_in(page, OWNER)
        shot(page, out, "01_workspace")
        page.goto(f"{UI}/app/orders/list")
        expect(page.get_by_text("Nothing to review")).to_be_visible(timeout=15000)
        shot(page, out, "01b_orders_empty")

        # 1. Imports through the review screen (declared meaning is restated by the person).
        import_file(page, "sales", SAMPLES / "sales_last_28_days.csv", {
            "The export covers sales from": (today - timedelta(days=28)).isoformat(),
            "…until (inclusive)": (today - timedelta(days=1)).isoformat()})
        shot(page, out, "02_import_sales_done")
        import_file(page, "inventory", SAMPLES / "stock_count.csv", {"This was true at": count_at})
        import_file(page, "open_orders", SAMPLES / "open_orders.csv", {
            "This was true at": now, "Quantities are counted in": "base", "This file lists": "suppliers_in_file"})
        page.goto(f"{UI}/app/settings/data")
        shot(page, out, "03_imports_applied")

        # 2. Plan.
        page.goto(f"{UI}/app/orders/plan")  # works the plan out on opening when there is none yet
        expect(page.get_by_text("Drafts to create")).to_be_visible(timeout=30000)
        shot(page, out, "04_plan")
        row = page.locator("tr", has_text="LITTER-20").first
        row.get_by_role("button", name="Why?").click()
        shot(page, out, "05_plan_why_litter")
        row.get_by_role("button", name="Hide").click()
        page.locator("li", has_text="Salmon cat food").first.get_by_role("button", name="Details").click()
        shot(page, out, "06_plan_on_hold_catfood")

        # 3. Drafts, one per supplier.
        page.get_by_role("button", name=re.compile("Create .* order draft")).click()
        expect(page.get_by_text(re.compile("PO-00001")).first).to_be_visible(timeout=15000)
        shot(page, out, "07_po_list_drafts")
        page.get_by_role("cell", name=re.compile("Phillips")).first.click()
        expect(page.get_by_role("heading", name="Items")).to_be_visible()
        shot(page, out, "08_po_draft")
        page.get_by_text("How the quantities were worked out").click()
        shot(page, out, "08b_po_line_basis")
        page.get_by_text("How the quantities were worked out").click()

        # 4. Edit a quantity -> new revision.
        page.get_by_label("Quantity for line 1").fill("8")
        page.get_by_role("button", name="Save quantities").click()
        expect(page.get_by_text(re.compile("version 2"))).to_be_visible(timeout=15000)
        shot(page, out, "09_po_edited_rev2")

        # 5. Submit and approve (owner), then the worker captures the test send.
        page.get_by_role("button", name="Submit for approval").click()
        approve = page.get_by_role("button", name=re.compile("Approve version 2"))
        expect(approve).to_be_enabled(timeout=15000)
        shot(page, out, "10_po_awaiting_approval")
        approve.click()
        expect(page.get_by_text(SENT_LABEL).first).to_be_visible(timeout=30000)
        shot(page, out, "11_po_test_sent")
        phillips_url = page.url
        page.reload()
        expect(page.get_by_text(SENT_LABEL).first).to_be_visible(timeout=15000)
        shot(page, out, "12_po_after_refresh")

        # 6. A manager can submit but cannot approve (button disabled; server answers 403).
        page.goto(f"{UI}/app/orders/list")
        coastal = page.get_by_role("cell", name=re.compile("Coastal")).first
        coastal.click()
        page.get_by_role("button", name="Submit for approval").click()
        expect(page.get_by_role("button", name=re.compile("Approve version"))).to_be_visible(timeout=15000)
        po_url = page.url
        sign_in(page, MANAGER)
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

        # 7. CP7: the supplier answers (mock reply, capture mode) — a person reviews the reading, then applies it.
        sign_in(page, OWNER)
        page.goto(phillips_url)
        page.get_by_role("button", name="Practice reply").click()
        page.get_by_label("Mock scenario").select_option("partial")
        page.get_by_role("button", name="Read reply").click()
        expect(page.get_by_role("button", name="Apply to the order")).to_be_visible(timeout=15000)
        shot(page, out, "14_reply_review_partial")
        page.get_by_role("button", name="Apply to the order").click()
        expect(page.get_by_text("Confirmed by supplier").first).to_be_visible(timeout=15000)
        shot(page, out, "15_reply_applied_inbound")

        # 8. The store plan now counts the confirmed 6 cases as arriving and drops the 2 that won't come.
        page.goto(f"{UI}/app/orders/plan")  # out of date → worked out again on opening
        expect(page.get_by_text("Worked out")).to_be_visible(timeout=30000)
        page.wait_for_timeout(2500)
        page.locator("tr", has_text="LITTER-20").first.get_by_role("button", name="Why?").click()
        shot(page, out, "16_plan_after_partial_acceptance")

        # 9. CP8: 5 of the 6 confirmed cases arrive, 1 damaged.
        page.goto(phillips_url.replace("/app/orders/", "/app/receiving/"))
        page.get_by_label("Arrived for line 1").fill("5")
        page.get_by_label("Damaged for line 1").fill("1")
        shot(page, out, "17_receiving_form")
        key = page.evaluate("() => sessionStorage.getItem('tabula.receipt-key.' + location.pathname.split('/').pop())")
        page.get_by_role("button", name="Record delivery").click()
        expect(page.get_by_text("added to Tabula stock")).to_be_visible(timeout=15000)
        shot(page, out, "18_receiving_recorded")
        # The same submit again (a retry, a second tab) with the key the form used: the same receipt, no double count.
        repeat = page.evaluate("""async (key) => {
            const s = JSON.parse(localStorage.getItem('tabula.session.v1'));
            const id = location.pathname.split('/').pop();
            const h = {'Content-Type': 'application/json', 'X-Dev-User': s.user, 'X-Tenant-Id': s.tenantId};
            const body = JSON.stringify({receipt_key: key, lines: [{line_no: 1, arrived_qty: '5', damaged_qty: '1'}]});
            const r = await fetch(`/v1/purchase-orders/${id}/receipts`, {method: 'POST', headers: h, body});
            const po = await (await fetch(`/v1/purchase-orders/${id}`, {headers: h})).json();
            return [r.status, po.progress.lines[0].received, po.progress.receipts.length];
        }""", key)
        print("same receipt again ->", repeat)
        assert repeat == [200, "5", 1]

        # 10. Recompute: the plan sees 4 sellable cases added to stock and 1 case still expected.
        page.goto(f"{UI}/app/orders/plan")  # out of date → worked out again on opening
        expect(page.get_by_text("Worked out")).to_be_visible(timeout=30000)
        page.wait_for_timeout(2500)
        page.locator("tr", has_text="LITTER-20").first.get_by_role("button", name="Why?").click()
        shot(page, out, "19_plan_after_receipt")

        # 11. Restart the PO worker, reload: state comes from the database.
        subprocess.run(["pkill", "-f", "clawbot.workflows.po_worker"], check=False)
        env = {**os.environ, "DATABASE_URL": os.getenv("DATABASE_URL", "postgresql+psycopg://localhost/tabula_dev"),
               "TABULA_ENV": "development", "TABULA_AUTH_MODE": "dev", "TABULA_SUPPLIER_SEND_MODE": "capture"}
        worker = subprocess.Popen([str(ROOT / ".venv/bin/python"), "-m", "clawbot.workflows.po_worker"], cwd=ROOT, env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        page.goto(phillips_url)
        expect(page.get_by_text("Partly received").first).to_be_visible(timeout=15000)
        shot(page, out, "20_po_after_worker_restart_and_reload")

        # 12. Another workspace cannot open this order.
        rival = page.evaluate("""async () => {
            const r = await fetch('/v1/stores', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Dev-User': 'rival@example.com'},
                body: JSON.stringify({name: 'Rival store', business_type: 'pet', timezone: 'America/New_York', currency: 'USD'})});
            return (await r.json()).tenant_id;
        }""")
        target = page.url
        demo_sign_in(page, "rival@example.com", tenant_id=rival)
        page.goto(target)
        expect(page.get_by_text(re.compile("not found", re.I)).first).to_be_visible(timeout=15000)
        shot(page, out, "21_other_workspace_404")
        browser.close()
        print(f"po_worker restarted by this walkthrough keeps running (pid {worker.pid})")


if __name__ == "__main__":
    main()
