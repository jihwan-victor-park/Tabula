"""
Read a Google Sheet once, as CSV, from a link the store shares.

Works without a Google account connection for sheets that are shared with "Anyone with the link"
or published to the web: the link is turned into Google's CSV export address and fetched. Only
Google's own hosts are contacted (also across redirects), so a pasted link cannot make the server
fetch anything else. Private sheets need a Google sign-in, which this build does not have — the
error says so instead of failing silently. No automatic re-sync: upload again to refresh.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import httpx

from clawbot.domain.errors import ValidationFailed

ALLOWED = ("docs.google.com",)
ALLOWED_SUFFIX = (".googleusercontent.com",)
MAX_BYTES = 10 * 1024 * 1024


def export_url(link: str) -> tuple[str, str]:
    """(CSV export URL, short name). Accepts edit/share links and publish-to-web links."""
    u = urlparse(link.strip())
    if u.scheme != "https" or u.hostname != "docs.google.com":
        raise ValidationFailed("Paste a Google Sheets link (https://docs.google.com/spreadsheets/…)")
    gid = parse_qs(u.query).get("gid", [None])[0] or (re.search(r"gid=(\d+)", u.fragment or "") or [None, None])[1]
    if gid is not None and not gid.isdigit():
        raise ValidationFailed("That does not look like a link to a Google Sheet")
    if m := re.match(r"^/spreadsheets/d/e/([A-Za-z0-9_-]+)/", u.path):
        return (f"https://docs.google.com/spreadsheets/d/e/{m[1]}/pub?output=csv" + (f"&gid={gid}" if gid else ""),
                f"sheet-{m[1][:8]}")
    if m := re.match(r"^/spreadsheets/d/([A-Za-z0-9_-]+)", u.path):
        return (f"https://docs.google.com/spreadsheets/d/{m[1]}/export?format=csv" + (f"&gid={gid}" if gid else ""),
                f"sheet-{m[1][:8]}")
    raise ValidationFailed("That does not look like a link to a Google Sheet")


def _allowed(url: str) -> bool:
    u = urlparse(url)
    host = u.hostname
    return u.scheme == "https" and bool(host) and (host in ALLOWED or any(host.endswith(s) for s in ALLOWED_SUFFIX))


NOT_SHARED = ("This sheet isn't shared publicly. In Google Sheets choose Share → “Anyone with the link” "
              "(viewer), or File → Download → CSV and upload the file instead.")


def fetch_csv(link: str, *, transport: httpx.BaseTransport | None = None) -> tuple[str, bytes]:
    url, name = export_url(link)
    with httpx.Client(timeout=20.0, follow_redirects=False, transport=transport) as http:
        for _ in range(5):
            if not _allowed(url):
                if urlparse(url).hostname == "accounts.google.com":  # Google asks for a sign-in: a private sheet
                    raise ValidationFailed(NOT_SHARED)
                raise ValidationFailed("Google redirected somewhere unexpected; download the sheet as CSV and upload it")
            with http.stream("GET", url) as resp:
                if resp.status_code in (301, 302, 303, 307, 308):
                    url = resp.headers.get("location", "")
                    continue
                if resp.status_code in (401, 403, 404) or "text/html" in resp.headers.get("content-type", ""):
                    raise ValidationFailed(NOT_SHARED)
                if resp.status_code != 200:
                    raise ValidationFailed(f"Google Sheets answered {resp.status_code}; try again or upload a CSV")
                body = bytearray()
                for chunk in resp.iter_bytes():  # stop reading as soon as the limit is passed
                    body += chunk
                    if len(body) > MAX_BYTES:
                        raise ValidationFailed("The sheet is larger than 10 MB")
                return f"{name}.csv", bytes(body)
        raise ValidationFailed("Too many redirects from Google")
