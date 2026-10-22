"""Shared steps for the browser walkthroughs (demo sign-in, store choice, file import)."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from playwright.sync_api import Page, expect

UI = "http://127.0.0.1:5173"
ROOT = Path(__file__).resolve().parents[1]
KIND_CARD = {"sales": "Sales history", "inventory": "Stock on hand", "open_orders": "Open orders",
             "supplier_price_list": "Supplier price list"}


def seed_demo_store(owner: str, *, imported: bool = False) -> str:
    """A fresh demo store owned by `owner` (python -m clawbot.devtools.seed_demo); returns its tenant id."""
    env = {**os.environ, "TABULA_ENV": "development", "TABULA_AUTH_MODE": "dev"}
    args = [str(ROOT / ".venv/bin/python"), "-m", "clawbot.devtools.seed_demo", "--owner", owner] + (["--import"] if imported else [])
    out = subprocess.run(args, cwd=ROOT, env=env, check=True, capture_output=True, text=True).stdout
    return re.search(r"^Workspace .* tenant (\S+)", out, re.M).group(1)


def demo_sign_in(page: Page, user: str, store: str | None = None, tenant_id: str | None = None) -> None:
    """Email-only demo sign-in (developer machine), then open the store by tenant id, by name, or the first one."""
    page.goto(f"{UI}/signin")
    page.evaluate("() => localStorage.removeItem('tabula.session.v1')")
    page.goto(f"{UI}/signin")
    page.get_by_role("button", name=re.compile("Demo sign-in")).click()
    box = page.locator("form").last.locator("input")
    box.fill(user)
    page.get_by_role("button", name="Continue").click()
    expect(page.get_by_role("heading", name="Your stores")).to_be_visible(timeout=15000)
    if tenant_id:  # names repeat across demo stores; the id doesn't
        page.evaluate("""async ([user, id]) => {
            const me = await (await fetch('/v1/me', {headers: {'X-Dev-User': user}})).json();
            const m = me.memberships.find((x) => x.tenant_id === id);
            localStorage.setItem('tabula.session.v1', JSON.stringify({user, tenantId: id, tenantName: m.tenant_name, isSample: m.is_sample}));
        }""", [user, tenant_id])
        page.goto(f"{UI}/app")
    elif store:
        page.get_by_role("button", name=re.compile(re.escape(store))).first.click()
    else:
        page.locator("button", has_text=re.compile(r"(Owner|Manager|Receiver|Bookkeeper)$", re.I)).first.click()
    page.wait_for_url(re.compile(r"/app$"), timeout=15000)


def import_file(page: Page, kind: str, path: Path, answers: dict[str, str], *, now: bool = False,
                suggested_dates: bool = False, shot_as=None) -> None:
    """Upload through the import wizard, answer its questions by label, import, wait until done."""
    page.goto(f"{UI}/app/data/import")
    page.get_by_role("button", name=re.compile(KIND_CARD[kind])).click()
    page.get_by_label("File").set_input_files(str(path))
    page.get_by_role("button", name="Check the file").click()
    expect(page.get_by_text("Columns we matched")).to_be_visible(timeout=15000)
    for label, value in answers.items():
        field = page.get_by_label(label)
        if field.evaluate("e => e.tagName") == "SELECT":
            field.select_option(value)
        elif field.get_attribute("type") == "checkbox":
            field.check()
        else:
            field.fill(value)
    if now:
        page.get_by_role("button", name="Now").click()
    if suggested_dates:
        page.get_by_text("Use these dates").click()
    if shot_as:
        shot_as()
    page.get_by_role("button", name=re.compile(r"^Import")).click()
    expect(page.get_by_text(re.compile(rf"{re.escape(path.name)} is in"))).to_be_visible(timeout=60000)
