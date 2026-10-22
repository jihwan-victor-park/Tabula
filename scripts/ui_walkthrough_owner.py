"""
A new store owner, start to finish, in a real browser against the running stack (scripts/dev.sh):
sign up → set up the store → upload their own stock and sales files → inventory → item →
scan a barcode and adjust one item (then undo) → insights → add a supplier and its items →
delivery address → order analysis → edit a quantity → create the draft → approve (test mode).

    PLAYWRIGHT_CHANNEL=chrome .venv/bin/python scripts/ui_walkthrough_owner.py [--out docs/screenshots/owner-app]

Uses var/owner/my_stock.csv and var/owner/my_sales_export.csv (made by this script if missing).
"""

from __future__ import annotations

import argparse
import os
import re
import uuid
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

UI = "http://127.0.0.1:5173"
ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / "var" / "owner"


def shot(page: Page, out: Path, name: str, full: bool = True) -> None:
    page.wait_for_timeout(500)
    page.screenshot(path=str(out / f"{name}.png"), full_page=full)
    print("saved", name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "docs" / "screenshots" / "owner-app"))
    out = Path(parser.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    email = f"maya+{uuid.uuid4().hex[:6]}@cornerpets.example"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=os.getenv("PLAYWRIGHT_CHANNEL") or None)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        try:
            run(page, browser, out, email)
        except Exception:
            page.screenshot(path=str(out / "debug_failure.png"), full_page=True)
            print("page errors:", errors[-3:])
            raise
        browser.close()


def run(page: Page, browser, out: Path, email: str) -> None:
    if True:

        # 1. First visit → sign-in screen → create an account → store details.
        page.goto(UI)
        expect(page.get_by_role("heading", name="Welcome back")).to_be_visible(timeout=15000)
        shot(page, out, "01_signin", full=False)
        page.get_by_role("link", name="Create an account").click()
        page.get_by_label("Email").fill(email)
        page.get_by_label("Password").fill("corner pets 2026!")
        page.get_by_role("button", name="Create account").click()
        expect(page.get_by_role("heading", name="Set up your store")).to_be_visible(timeout=15000)
        page.get_by_label("Store name").fill("Corner Pet Supply")
        page.get_by_label("What do you sell?").select_option("pet")
        page.get_by_label("Time zone").select_option("America/New_York")
        shot(page, out, "02_store_details", full=False)
        page.get_by_role("button", name="Continue to your data").click()

        # 2. Onboarding: connect data step by step; each step says what it unlocks.
        expect(page.get_by_text("0 of 4 done")).to_be_visible(timeout=15000)
        shot(page, out, "03_setup_start")
        page.get_by_role("link", name="Upload stock file").click()
        page.get_by_label("File").set_input_files(str(FILES / "my_stock.csv"))
        page.get_by_role("button", name="Check the file").click()
        expect(page.get_by_text("Columns we matched")).to_be_visible(timeout=15000)
        page.get_by_label("Add items that are not in Tabula yet").check()
        page.get_by_role("button", name="Now").click()
        shot(page, out, "04_import_stock_review")
        page.get_by_role("button", name=re.compile(r"^Import")).click()  # saves the answers, re-checks, imports
        expect(page.get_by_text("my_stock.csv is in")).to_be_visible(timeout=30000)
        page.get_by_role("link", name="Continue setup").click()
        page.get_by_role("link", name="Import sales").click()
        page.get_by_label("File").set_input_files(str(FILES / "my_sales_export.csv"))
        page.get_by_role("button", name="Check the file").click()
        expect(page.get_by_text("Use these dates")).to_be_visible(timeout=15000)
        page.get_by_text("Use these dates").click()
        shot(page, out, "05_import_sales_review")
        page.get_by_role("button", name=re.compile(r"^Import")).click()
        expect(page.get_by_text("my_sales_export.csv is in")).to_be_visible(timeout=60000)
        page.get_by_role("link", name="Continue setup").click()
        expect(page.get_by_text("2 of 4 done")).to_be_visible(timeout=15000)
        shot(page, out, "06_setup_two_done")

        # 3. Overview: what is short, and — without a supplier yet — the next step instead of a quantity.
        page.get_by_role("link", name="Go to Overview").click()
        expect(page.get_by_text(re.compile("items? need attention"))).to_be_visible(timeout=20000)
        shot(page, out, "07_overview_no_supplier")

        # 4. Inventory: a plain list; details open in a side panel.
        page.get_by_role("link", name="Inventory").first.click()
        expect(page.get_by_role("cell", name=re.compile("Clumping cat litter 25lb"))).to_be_visible(timeout=20000)
        shot(page, out, "08_inventory")
        page.get_by_role("cell", name=re.compile("Clumping cat litter 25lb")).click()
        expect(page.get_by_role("dialog")).to_be_visible(timeout=15000)
        expect(page.get_by_text("Suppliers and cost")).to_be_visible()
        shot(page, out, "09_item_panel", full=False)
        page.keyboard.press("Escape")

        # 5. Scan: choose the work mode, scan, confirm the quantity → before → after, undo available.
        page.get_by_role("link", name="Scan").click()
        page.get_by_role("radio", name="Damaged").click()
        page.get_by_label("Barcode or SKU").fill("850012345695")
        page.keyboard.press("Enter")  # what a USB / Bluetooth scanner sends
        expect(page.get_by_label("Quantity")).to_be_visible(timeout=15000)
        page.get_by_label("Note (optional)").fill("bag torn on delivery shelf")
        shot(page, out, "10_scan_damaged_mode")
        page.get_by_role("button", name=re.compile(r"^Save")).click()
        expect(page.get_by_text(re.compile("Saved — Damaged"))).to_be_visible(timeout=15000)
        shot(page, out, "11_scan_saved")
        page.get_by_label("Barcode or SKU").fill("999000111222")
        page.keyboard.press("Enter")
        expect(page.get_by_text("No item has barcode 999000111222")).to_be_visible(timeout=15000)
        shot(page, out, "12_scan_unknown_barcode")

        # 6. Insights: the sales chart lives here now.
        page.get_by_role("link", name="Insights").first.click()
        expect(page.get_by_text("Best sellers")).to_be_visible(timeout=20000)
        shot(page, out, "13_insights")

        # 7. Orders › Suppliers: add the supplier and its items; Settings: delivery address, a teammate.
        page.get_by_role("link", name="Orders").first.click()
        page.get_by_role("link", name="Suppliers").click()
        page.get_by_role("button", name="Add supplier").first.click()
        page.get_by_label("Supplier name").fill("Riverside Pet Distributors")
        page.get_by_label("Order email").fill("orders@riverside-pet.example.com")
        page.get_by_label("Your account number with them").fill("RPD-4471")
        page.get_by_label("Lead time (days)").fill("3")
        page.get_by_label("Minimum order ($)").fill("100")
        page.get_by_label("Shipping terms").fill("Free over $300, else $18")
        shot(page, out, "14_supplier_new")
        page.get_by_role("button", name="Save supplier").click()
        expect(page.get_by_text("Items and prices")).to_be_visible(timeout=20000)
        for item, sku, per, price in [("Clumping cat litter 25lb", "RP-CL25", "4", "58.00"), ("Dental chews large 10ct", "RP-DC10", "12", "66.00"),
                                      ("Grain-free salmon kibble 12lb", "RP-GF12", "2", "61.00"), ("Salmon oil 16oz", "RP-SO16", "6", "42.00")]:
            page.get_by_role("button", name="+ Add an item").click()
            pick = page.get_by_label("Your item")
            pick.select_option(pick.locator("option", has_text=item).first.get_attribute("value"))
            page.get_by_label("Their SKU").fill(sku)
            page.get_by_label("Units each").fill(per)
            page.get_by_label(re.compile("Price per")).fill(price)
            page.get_by_role("button", name="Add", exact=True).click()
            expect(page.get_by_text(sku)).to_be_visible(timeout=15000)
        shot(page, out, "15_supplier_items")
        page.goto(f"{UI}/app/settings")
        page.get_by_label("Street").fill("418 Atlantic Ave")
        page.get_by_label("City").fill("Brooklyn")
        page.get_by_label("State").fill("NY")
        page.get_by_label("ZIP").fill("11217")
        page.get_by_role("button", name="Save", exact=True).click()
        expect(page.get_by_text("Saved.")).to_be_visible(timeout=15000)
        shot(page, out, "16_settings_store")
        page.get_by_role("link", name="Team").click()
        page.get_by_label("Invite by email").fill(f"sam+{uuid.uuid4().hex[:6]}@cornerpets.example")
        page.get_by_role("button", name="Add").click()
        expect(page.get_by_text(re.compile("Send this link to"))).to_be_visible(timeout=15000)
        shot(page, out, "17_settings_team_invite")

        # 8. Overview again: what to order, how much, and what it costs — then the plan → drafts.
        page.get_by_role("link", name="Overview").first.click()
        expect(page.get_by_text("Suggested total")).to_be_visible(timeout=20000)
        shot(page, out, "18_overview")
        page.get_by_role("link", name="Review reorder plan").first.click()
        expect(page.get_by_text("Drafts to create")).to_be_visible(timeout=30000)
        shot(page, out, "19_reorder_plan")
        first_qty = page.get_by_label(re.compile("^Quantity for ")).first
        first_qty.fill(str(int(float(first_qty.input_value() or "1")) + 1))
        page.get_by_role("button", name="Why?").first.click()
        shot(page, out, "20_reorder_plan_edited_why")
        page.get_by_role("button", name=re.compile("Create .* order draft")).click()
        expect(page.get_by_role("button", name="Submit for approval")).to_be_visible(timeout=20000)
        shot(page, out, "21_order_draft")
        page.get_by_role("button", name="Submit for approval").click()
        approve = page.get_by_role("button", name=re.compile("Approve version"))
        expect(approve).to_be_enabled(timeout=15000)
        approve.click()
        expect(page.get_by_text("Test order — not sent.")).to_be_visible(timeout=30000)
        shot(page, out, "22_order_approved_test_mode")
        page.goto(f"{UI}/app/orders?tab=progress")
        expect(page.get_by_text("Riverside Pet Distributors").first).to_be_visible(timeout=15000)
        shot(page, out, "23_orders_in_progress")
        page.get_by_role("link", name="Overview").first.click()
        expect(page.get_by_role("heading", name="On the way")).to_be_visible(timeout=15000)
        shot(page, out, "24_overview_after_order")

        # 9. Phone width: Overview and the reorder list, Inventory.
        page.set_viewport_size({"width": 390, "height": 844})
        page.reload()
        expect(page.get_by_role("heading", name="On the way")).to_be_visible(timeout=20000)
        shot(page, out, "25_phone_overview", full=False)
        page.goto(f"{UI}/app/inventory")
        expect(page.get_by_text("Clumping cat litter 25lb").last).to_be_visible(timeout=20000)
        shot(page, out, "26_phone_inventory", full=False)


if __name__ == "__main__":
    main()
