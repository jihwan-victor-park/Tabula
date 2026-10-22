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

        # 1. First visit → sign-in screen → create an account.
        page.goto(UI)
        expect(page.get_by_role("heading", name="Welcome back")).to_be_visible(timeout=15000)
        shot(page, out, "01_signin", full=False)
        page.get_by_role("link", name="Create an account").click()
        page.get_by_label("Email").fill(email)
        page.get_by_label("Password").fill("corner pets 2026!")
        shot(page, out, "02_signup", full=False)
        page.get_by_role("button", name="Create account").click()

        # 2. Store setup → straight to data.
        expect(page.get_by_role("heading", name="Set up your store")).to_be_visible(timeout=15000)
        page.get_by_label("Store name").fill("Corner Pet Supply")
        page.get_by_label("What do you sell?").select_option("pet")
        page.get_by_label("Time zone").select_option("America/New_York")
        shot(page, out, "03_store_setup", full=False)
        page.get_by_role("button", name="Continue to your data").click()
        expect(page.get_by_role("heading", name="Bring in your data")).to_be_visible(timeout=15000)
        shot(page, out, "04_data_sources")

        # 3. Their own stock file: auto-matched columns, unused ones explained, a couple of questions.
        page.get_by_role("button", name="Upload a file").click()
        page.get_by_role("button", name=re.compile("Stock on hand")).click()
        page.get_by_label("File").set_input_files(str(FILES / "my_stock.csv"))
        page.get_by_role("button", name="Check the file").click()
        expect(page.get_by_text("Columns we matched")).to_be_visible(timeout=15000)
        page.get_by_label("Add items that are not in Tabula yet").check()
        page.get_by_role("button", name="Now").click()
        shot(page, out, "05_import_stock_review")
        page.get_by_role("button", name=re.compile(r"^Import")).click()  # saves the answers, re-checks, imports
        expect(page.get_by_text("my_stock.csv is in")).to_be_visible(timeout=30000)
        shot(page, out, "06_import_stock_done", full=False)

        # 4. Sales history: the file's own dates are suggested; the owner confirms.
        page.get_by_role("button", name="Import another file").click()
        page.get_by_role("button", name=re.compile("Sales history")).click()
        page.get_by_label("File").set_input_files(str(FILES / "my_sales_export.csv"))
        page.get_by_role("button", name="Check the file").click()
        expect(page.get_by_text("Use these dates")).to_be_visible(timeout=15000)
        shot(page, out, "07_import_sales_review")
        page.get_by_text("Use these dates").click()
        page.get_by_role("button", name=re.compile(r"^Import")).click()
        expect(page.get_by_text("my_sales_export.csv is in")).to_be_visible(timeout=60000)

        # 5. Home and inventory.
        page.goto(f"{UI}/app")
        expect(page.get_by_text("Sales, last 14 days")).to_be_visible(timeout=20000)
        shot(page, out, "08_home")
        page.goto(f"{UI}/app/inventory")
        expect(page.get_by_text("Clumping cat litter 25lb").first).to_be_visible(timeout=20000)
        shot(page, out, "09_inventory")
        page.get_by_text("Clumping cat litter 25lb").first.click()
        expect(page.get_by_text("Daily sales (6 weeks)")).to_be_visible(timeout=15000)
        shot(page, out, "10_item_detail")

        # 6. Scan a barcode → choose what happened → saved with who/why → undo.
        page.goto(f"{UI}/app/scan")
        page.get_by_label("Barcode or SKU").fill("850012345695")
        page.keyboard.press("Enter")  # what a USB / Bluetooth scanner sends
        expect(page.get_by_text("Clumping cat litter 25lb").first).to_be_visible(timeout=15000)
        shot(page, out, "11_scan_found")
        page.get_by_role("button", name=re.compile("^Damaged")).click()
        page.get_by_label("Quantity").fill("1")
        page.get_by_label("Reason / note (optional)").fill("bag torn on delivery shelf")
        page.get_by_role("button", name=re.compile("— save")).click()
        expect(page.get_by_text(re.compile("Saved: -1"))).to_be_visible(timeout=15000)
        shot(page, out, "12_scan_saved")
        page.get_by_label("Barcode or SKU").fill("999000111222")
        page.keyboard.press("Enter")
        expect(page.get_by_text("No item has barcode 999000111222")).to_be_visible(timeout=15000)
        shot(page, out, "13_scan_unknown_barcode")

        # 7. Insights.
        page.goto(f"{UI}/app/insights")
        expect(page.get_by_text("Best sellers")).to_be_visible(timeout=20000)
        shot(page, out, "14_insights")

        # 8. Order analysis before a supplier exists: says what is missing.
        page.goto(f"{UI}/app/orders")
        page.get_by_role("button", name=re.compile("Run order analysis")).click()
        expect(page.get_by_text("To turn suggestions into orders")).to_be_visible(timeout=30000)
        shot(page, out, "15_orders_missing_supplier")

        # 9. Add a supplier and its items; add the delivery address.
        page.goto(f"{UI}/app/suppliers")
        page.get_by_role("button", name="Add supplier").first.click()
        page.get_by_label("Supplier name").fill("Riverside Pet Distributors")
        page.get_by_label("Order email").fill("orders@riverside-pet.example.com")
        page.get_by_label("Your account number with them").fill("RPD-4471")
        page.get_by_label("Lead time (days)").fill("3")
        page.get_by_label("Minimum order ($)").fill("100")
        page.get_by_label("Shipping terms").fill("Free over $300, else $18")
        shot(page, out, "16_supplier_new")
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
        shot(page, out, "17_supplier_items")
        page.goto(f"{UI}/app/settings")
        page.get_by_label("Street").fill("418 Atlantic Ave")
        page.get_by_label("City").fill("Brooklyn")
        page.get_by_label("State").fill("NY")
        page.get_by_label("ZIP").fill("11217")
        page.get_by_role("button", name="Save", exact=True).click()
        expect(page.get_by_text("Saved.")).to_be_visible(timeout=15000)
        # A teammate: the owner gets a one-time link to pass on (nobody else can claim the email).
        page.get_by_label("Invite by email").fill(f"sam+{uuid.uuid4().hex[:6]}@cornerpets.example")
        page.get_by_role("button", name="Add").click()
        expect(page.get_by_text(re.compile("Send this link to"))).to_be_visible(timeout=15000)
        shot(page, out, "18_settings")

        # 10. Order analysis → change one quantity → draft → approve (test mode).
        page.goto(f"{UI}/app/orders")
        page.get_by_role("button", name=re.compile("Run again|Run order analysis")).click()
        page.wait_for_timeout(2500)
        expect(page.get_by_text("Suggested orders")).to_be_visible(timeout=30000)
        shot(page, out, "19_order_suggestions")
        first_qty = page.get_by_label(re.compile("^Quantity for ")).first
        first_qty.fill(str(int(float(first_qty.input_value() or "1")) + 1))
        page.get_by_role("button", name="Why?").first.click()
        shot(page, out, "20_order_suggestions_edited_why")
        page.get_by_role("button", name=re.compile("Create .* order draft")).click()
        expect(page.get_by_role("button", name="Submit for approval")).to_be_visible(timeout=20000)
        shot(page, out, "21_order_draft")
        page.get_by_role("button", name="Submit for approval").click()
        approve = page.get_by_role("button", name=re.compile("Approve version"))
        expect(approve).to_be_enabled(timeout=15000)
        approve.click()
        expect(page.get_by_text(re.compile(r"Sent \(test mode\)")).first).to_be_visible(timeout=30000)
        shot(page, out, "22_order_approved_test_mode")

        # 11. Phone width: home and scan.
        phone = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        phone.context.add_cookies(page.context.cookies())
        phone.goto(f"{UI}/app")
        phone.evaluate("(s) => localStorage.setItem('tabula.session.v1', s)", page.evaluate("localStorage.getItem('tabula.session.v1')"))
        phone.goto(f"{UI}/app")
        expect(phone.get_by_text("Runs out soonest")).to_be_visible(timeout=20000)
        shot(phone, out, "23_phone_home", full=False)
        phone.goto(f"{UI}/app/inventory")
        expect(phone.get_by_text("Clumping cat litter 25lb").last).to_be_visible(timeout=20000)
        shot(phone, out, "24_phone_inventory", full=False)


if __name__ == "__main__":
    main()
