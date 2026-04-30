"""
Inbox listener — polls ~/Library/Messages/chat.db for new inbound iMessages
and forwards them to a downstream HTTP endpoint (e.g. the Universal Agent).

Requires Full Disk Access for the Terminal.app process on macOS 10.14+.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

DB_PATH = Path.home() / "Library" / "Messages" / "chat.db"


def _normalize(number: str) -> str:
    """Strip formatting and keep the last 10 digits for comparison."""
    digits = "".join(c for c in number if c.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def _matches(handle_id: str, watched_numbers: list[str]) -> bool:
    norm_handle = _normalize(handle_id)
    for w in watched_numbers:
        if norm_handle and (norm_handle == w or w.endswith(norm_handle) or norm_handle.endswith(w)):
            return True
    return False


def _get_max_rowid() -> int:
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
        row = conn.execute("SELECT MAX(ROWID) FROM message").fetchone()
        conn.close()
        return row[0] or 0
    except Exception:
        return 0


class InboxListener:
    """
    Background thread that watches chat.db for new incoming messages from
    watched_numbers and POSTs them to forward_url.
    """

    def __init__(
        self,
        watched_numbers: list[str],
        forward_url: str,
        business_name: str,
        business_location: str,
        poll_interval: float = 3.0,
    ) -> None:
        self.watched_numbers = [_normalize(n) for n in watched_numbers]
        self.forward_url = forward_url
        self.business_name = business_name
        self.business_location = business_location
        self.poll_interval = poll_interval
        self._last_rowid = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        # Initialise cursor to current end of table so we only see *new* messages
        self._last_rowid = _get_max_rowid()
        print(
            f"[inbox] Watching {self.watched_numbers} from rowid {self._last_rowid} "
            f"→ {self.forward_url}"
        )
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._poll()
            except Exception as exc:
                print(f"[inbox] poll error: {exc}")
            time.sleep(self.poll_interval)

    def _poll(self) -> None:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
        try:
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
                (self._last_rowid,),
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return

        self._last_rowid = rows[-1][0]

        for _rowid, text, handle_id in rows:
            if not _matches(handle_id, self.watched_numbers):
                continue
            print(f"[inbox] New message from {handle_id}: {text!r}")
            self._forward(handle_id, text)

    def _forward(self, sender: str, text: str) -> None:
        payload = {
            "message": text,
            "business_name": self.business_name,
            "location": self.business_location,
            "recipient": sender,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.forward_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                print(f"[inbox] Forwarded to universal agent → {resp.status}")
        except Exception as exc:
            print(f"[inbox] Forward failed: {exc}")
