"""
Shared message delivery utility.

Delivery priority:
1. Clawbot API  — POST http://localhost:8000/message/send
   Clawbot runs from Terminal (which has Messages Automation permission), so any
   agent can deliver iMessages simply by calling this endpoint. No per-process
   permission setup needed.
2. osascript (direct fallback) — only works if the calling process already has
   Automation → Messages permission.
"""

from __future__ import annotations

import os
import subprocess

import httpx

CLAWBOT_URL = os.getenv("CLAWBOT_URL", "http://localhost:8007")


def _send_via_clawbot(recipient: str, message: str) -> bool:
    try:
        resp = httpx.post(
            f"{CLAWBOT_URL}/message/send",
            json={"recipient": recipient, "message": message},
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json().get("sent", False)
        return False
    except Exception:
        return False


def _send_via_osascript(recipient: str, message: str) -> bool:
    safe = message.replace("\\", "\\\\").replace('"', '\\"')
    script = (
        'tell application "Messages"\n'
        f'    send "{safe}" to buddy "{recipient}" '
        'of (1st service whose service type = iMessage)\n'
        'end tell'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0
    except Exception:
        return False


def send_message(recipient: str, message: str) -> tuple[bool, str | None]:
    """
    Send a message. Tries clawbot first, then falls back to direct osascript.

    Returns (sent: bool, error: str | None).
    """
    if _send_via_clawbot(recipient, message):
        return True, None

    if _send_via_osascript(recipient, message):
        return True, None

    return False, (
        "iMessage delivery failed. Start clawbot from Terminal.app so it has "
        "Automation permission: python -m clawbot.main serve-api"
    )
