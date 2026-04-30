"""
Onboarding CLI — personalizes the iMessage digest agent via a back-and-forth
iMessage conversation with the business owner.

Usage:
    python onboarding_cli.py --to +15551234567

What it does:
    1. Sends each setup question to the owner via iMessage.
    2. Waits for their reply (polls chat.db).
    3. Saves the collected config to .openclaw/onboarding.json.

Requirements:
    - clawbot serve-api must be running (or Terminal.app has Messages permission).
    - Full Disk Access granted to the Terminal.app process.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))

from clawbot.tools.messaging import send_message

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CHAT_DB = Path.home() / "Library" / "Messages" / "chat.db"
ONBOARDING_PATH = Path(__file__).parent / ".openclaw" / "onboarding.json"
OPENCLAW_DIR = Path(__file__).parent / ".openclaw"
REPLY_TIMEOUT = 120   # seconds to wait for each reply
POLL_INTERVAL = 2     # seconds between chat.db polls


# ---------------------------------------------------------------------------
# chat.db helpers
# ---------------------------------------------------------------------------


def _normalize(number: str) -> str:
    digits = "".join(c for c in number if c.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def _get_max_rowid() -> int:
    try:
        conn = sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)
        row = conn.execute("SELECT MAX(ROWID) FROM message").fetchone()
        conn.close()
        return row[0] or 0
    except Exception:
        return 0


def _wait_for_reply(from_number: str, after_rowid: int, timeout: int = REPLY_TIMEOUT) -> str | None:
    """
    Block until a new iMessage arrives from from_number, or timeout expires.
    Returns the message text, or None on timeout.
    """
    norm = _normalize(from_number)
    deadline = time.time() + timeout
    last_rowid = after_rowid

    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        try:
            conn = sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)
            rows = conn.execute(
                """
                SELECT m.ROWID, m.text, h.id
                FROM message m
                JOIN handle h ON m.handle_id = h.ROWID
                WHERE m.ROWID > ?
                  AND m.is_from_me = 0
                  AND m.text IS NOT NULL
                  AND m.text != ''
                ORDER BY m.ROWID ASC
                """,
                (last_rowid,),
            ).fetchall()
            conn.close()
        except Exception:
            continue

        for rowid, text, handle_id in rows:
            last_rowid = max(last_rowid, rowid)
            if _normalize(handle_id).endswith(norm) or norm.endswith(_normalize(handle_id)):
                return text.strip()

    return None


# ---------------------------------------------------------------------------
# Question / answer flow
# ---------------------------------------------------------------------------


def ask(recipient: str, question: str, after_rowid: int) -> tuple[str | None, int]:
    """
    Send question via iMessage, then wait for a reply.
    Returns (reply_text, new_max_rowid).
    """
    sent, err = send_message(recipient, question)
    if not sent:
        print(f"[onboarding] Failed to send message: {err}")
        return None, after_rowid

    print(f"  → Sent. Waiting for reply (up to {REPLY_TIMEOUT}s)…")
    new_rowid = _get_max_rowid()
    reply = _wait_for_reply(recipient, after_rowid=new_rowid, timeout=REPLY_TIMEOUT)
    return reply, _get_max_rowid()


def _parse_categories(raw: str) -> list[str]:
    """Turn a comma/newline separated reply into a clean list."""
    parts = [p.strip().strip("•-–").strip() for p in raw.replace("\n", ",").split(",")]
    return [p for p in parts if p]


# ---------------------------------------------------------------------------
# Save / load
# ---------------------------------------------------------------------------


def save_config(config: dict) -> None:
    ONBOARDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    config["completed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(ONBOARDING_PATH, "w") as f:
        json.dump(config, f, indent=2)
    print(f"\n[onboarding] Config saved to {ONBOARDING_PATH}")


def load_config() -> dict | None:
    if ONBOARDING_PATH.exists():
        with open(ONBOARDING_PATH) as f:
            return json.load(f)
    return None


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------


QUESTIONS = [
    {
        "key": "business_name",
        "text": (
            "Hey! I'm setting up your business digest. "
            "What's the name of your business?"
        ),
    },
    {
        "key": "location",
        "text": "What city and state is your business in? (e.g. Austin, TX)",
    },
    {
        "key": "categories_raw",
        "text": (
            "What product categories should I track for trends and pricing? "
            "Send them as a comma-separated list (e.g. LEGO, Puzzles, Board Games)"
        ),
    },
    {
        "key": "digest_time",
        "text": (
            "What time should I send your daily digest? "
            "Reply with a time like '8am' or '9:30am'."
        ),
    },
    {
        "key": "include_trends",
        "text": (
            "Should I include trend analysis in your digest? "
            "Reply YES or NO."
        ),
    },
    {
        "key": "include_procurement",
        "text": (
            "Should I include supplier/procurement recommendations? "
            "Reply YES or NO."
        ),
    },
    {
        "key": "agent_name",
        "text": (
            "Now let's set up your personal agent. "
            "What would you like to name it? (e.g. Scout, Max, Aria)"
        ),
    },
    {
        "key": "agent_style",
        "text": (
            "How should your agent communicate? Reply with a number:\n"
            "1) Super brief & direct\n"
            "2) Friendly & conversational\n"
            "3) Detailed & thorough"
        ),
    },
    {
        "key": "agent_priority",
        "text": (
            "What matters most to you? Reply with a number:\n"
            "1) Saving money\n"
            "2) Speed & quick answers\n"
            "3) Quality suppliers & reliability"
        ),
    },
    {
        "key": "agent_role",
        "text": "In one sentence, how would you describe your agent's role to your team?",
    },
]


# ---------------------------------------------------------------------------
# Per-user file paths
# ---------------------------------------------------------------------------

def _safe_filename(recipient: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_+]", "_", recipient)


def _identity_path(recipient: str) -> Path:
    return OPENCLAW_DIR / f"identity_{_safe_filename(recipient)}.md"


def _soul_path(recipient: str) -> Path:
    return OPENCLAW_DIR / f"soul_{_safe_filename(recipient)}.md"


def _memory_path(recipient: str) -> Path:
    return OPENCLAW_DIR / f"memory_{_safe_filename(recipient)}.md"


# ---------------------------------------------------------------------------
# Generate IDENTITY.md and SOUL.md via Claude
# ---------------------------------------------------------------------------

def _style_label(raw: str) -> str:
    if "1" in raw:
        return "super brief and direct"
    if "3" in raw:
        return "detailed and thorough"
    return "friendly and conversational"


def _priority_label(raw: str) -> str:
    if "1" in raw:
        return "saving money"
    if "3" in raw:
        return "quality suppliers and reliability"
    return "speed and quick answers"


def generate_agent_files(config: dict) -> None:
    """Use Claude to generate IDENTITY.md and SOUL.md, then write initial MEMORY.md."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[onboarding] ANTHROPIC_API_KEY not set — skipping agent file generation.")
        return

    client = anthropic.Anthropic(api_key=api_key)
    recipient = config["recipient"]
    name = config.get("agent_name", "Scout")
    style = _style_label(config.get("agent_style", "2"))
    priority = _priority_label(config.get("agent_priority", "2"))
    role = config.get("agent_role", "my business assistant")
    business = config.get("business_name", "my business")
    location = config.get("location", "")
    cats = ", ".join(config.get("categories", [])) or "general products"

    print(f"[onboarding] Generating IDENTITY.md and SOUL.md for {name}...")

    prompt = f"""You are helping set up a personalized AI business agent for a small business owner.

Here is what the owner told us during onboarding:
- Agent name: {name}
- Business: {business}, {location}
- Product categories: {cats}
- Communication style: {style}
- Top priority: {priority}
- Role description: {role}

Generate two markdown files:

--- IDENTITY.md ---
Write a short identity file (under 150 words) that defines:
- The agent's name and role
- How it introduces itself in a first message
- Its relationship to the business owner

--- SOUL.md ---
Write a soul file (under 200 words) that defines:
- Core values aligned with the owner's priorities
- Communication style (matching what the owner chose)
- Tone and vibe
- What the agent optimizes for
- What it never does

Respond with exactly this format — no extra text:
=== IDENTITY.md ===
[content]
=== SOUL.md ===
[content]"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()

    # Parse the two sections
    identity_content = ""
    soul_content = ""
    if "=== IDENTITY.md ===" in raw and "=== SOUL.md ===" in raw:
        parts = raw.split("=== SOUL.md ===")
        identity_content = parts[0].replace("=== IDENTITY.md ===", "").strip()
        soul_content = parts[1].strip()
    else:
        print("[onboarding] Warning: could not parse Claude response, using defaults.")
        identity_content = f"# {name}\n\nI am {name}, your business assistant for {business}."
        soul_content = f"# Soul\n\nCommunication style: {style}.\nTop priority: {priority}."

    OPENCLAW_DIR.mkdir(parents=True, exist_ok=True)

    _identity_path(recipient).write_text(identity_content, encoding="utf-8")
    print(f"[onboarding] Wrote {_identity_path(recipient).name}")

    _soul_path(recipient).write_text(soul_content, encoding="utf-8")
    print(f"[onboarding] Wrote {_soul_path(recipient).name}")

    # Write initial blank MEMORY.md
    if not _memory_path(recipient).exists():
        _memory_path(recipient).write_text(
            f"# Memory — {business}\n\n"
            f"Business: {business}, {location}\n"
            f"Categories: {cats}\n\n"
            "## Notes\n\n_Nothing recorded yet._\n",
            encoding="utf-8",
        )
        print(f"[onboarding] Wrote {_memory_path(recipient).name}")


def run_onboarding(recipient: str, force: bool = False) -> None:
    existing = load_config()
    if existing and not force:
        print(f"[onboarding] Already completed at {existing.get('completed_at')}.")
        print(f"  Business: {existing.get('business_name')}, {existing.get('location')}")
        print(f"  Use --force to redo onboarding.")
        return

    print(f"[onboarding] Starting onboarding with {recipient}")
    print(f"  chat.db: {CHAT_DB}")
    if not CHAT_DB.exists():
        print("[onboarding] ERROR: chat.db not found. Grant Full Disk Access to Terminal.app.")
        sys.exit(1)

    cursor = _get_max_rowid()
    config: dict = {"recipient": recipient}

    for q in QUESTIONS:
        reply, cursor = ask(recipient, q["text"], after_rowid=cursor)
        if reply is None:
            print(f"[onboarding] Timed out waiting for answer to '{q['key']}'. Aborting.")
            sys.exit(1)
        print(f"  ← {reply!r}")
        config[q["key"]] = reply

    # Post-process
    config["categories"] = _parse_categories(config.pop("categories_raw", ""))
    config["include_trends"] = config.get("include_trends", "yes").lower().startswith("y")
    config["include_procurement"] = config.get("include_procurement", "yes").lower().startswith("y")

    save_config(config)

    # Generate per-user IDENTITY.md, SOUL.md, MEMORY.md
    generate_agent_files(config)

    # Send confirmation
    cats = ", ".join(config["categories"]) or "none"
    agent_name = config.get("agent_name", "your agent")
    confirm = (
        f"Got it! Here's your setup:\n"
        f"Business: {config['business_name']}, {config['location']}\n"
        f"Categories: {cats}\n"
        f"Daily digest at: {config.get('digest_time', 'not set')}\n"
        f"Agent name: {agent_name}\n"
        f"You're all set! Say hi to {agent_name} anytime."
    )
    send_message(recipient, confirm)
    print("\n[onboarding] Complete!")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Onboard a business owner via iMessage.")
    parser.add_argument(
        "--to",
        required=True,
        metavar="PHONE",
        help="iMessage phone number or Apple ID to onboard, e.g. +15551234567",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run onboarding even if already completed.",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Print the saved onboarding config and exit.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.show:
        config = load_config()
        if config:
            print(json.dumps(config, indent=2))
        else:
            print("No onboarding config found.")
        return

    run_onboarding(recipient=args.to, force=args.force)


if __name__ == "__main__":
    main()
