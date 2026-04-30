from __future__ import annotations

import subprocess


def send_imessage(recipient: str, message: str) -> tuple[bool, str | None]:
    """
    Send an iMessage via AppleScript (osascript).

    Clawbot must be started from a process (e.g. Terminal.app) that has been
    granted Automation → Messages permission in System Settings.
    All other agents POST to clawbot's /message/send endpoint so the permission
    lives here, not in every agent process.

    Returns (sent: bool, error: str | None).
    """
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
        if result.returncode == 0:
            return True, None
        return False, result.stderr.strip() or "osascript exited non-zero"
    except Exception as exc:
        return False, str(exc)
