"""
Fail if staged (or all tracked) files contain credentials or runtime identity files.

  python scripts/secret_scan.py          # staged files (pre-commit hook)
  python scripts/secret_scan.py --all    # every tracked file (CI / tests)

Prints file, line and pattern name only — never the matched value.
"""

from __future__ import annotations

import re
import subprocess
import sys

PATTERNS = {
    "anthropic_api_key": r"sk-ant-[A-Za-z0-9_\-]{20,}",
    "openai_api_key": r"sk-(?:proj-)?[A-Za-z0-9]{32,}",
    "aws_access_key": r"AKIA[0-9A-Z]{16}",
    "github_token": r"gh[pousr]_[A-Za-z0-9]{30,}",
    "twilio_account_sid": r"\bAC[a-f0-9]{32}\b",
    "slack_token": r"xox[abpr]-[A-Za-z0-9-]{10,}",
    "google_api_key": r"AIza[0-9A-Za-z_\-]{35}",
    "stripe_secret_key": r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}",
    "square_access_token": r"\bEAAA[A-Za-z0-9_\-]{40,}",
    "private_key_block": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "uri_with_password": r"\b(?:mongodb(?:\+srv)?|postgres(?:ql)?(?:\+\w+)?|redis|amqp)://[^:\s/@]+:[^@\s/]{3,}@",
    "json_token_value": r"\"(?:token|secret|password|apiKey|api_key|accessToken)\"\s*:\s*\"[A-Za-z0-9_\-\.]{24,}\"",
}
FORBIDDEN_PATHS = (
    re.compile(r"^\.openclaw/(identity|devices|logs|memory)/"),
    re.compile(r"^\.openclaw/agents/[^/]+/(sessions|agent)/"),
    re.compile(r"^\.openclaw/openclaw\.json(\.bak.*)?$"),
    re.compile(r"(^|/)\.env$"),
    re.compile(r"\.(pem|key|p12)$"),
)
ALLOW_MARKER = "secret-scan: allow"  # for test fixtures that must contain a fake pattern


def _files(all_tracked: bool) -> list[str]:
    cmd = ["git", "ls-files"] if all_tracked else ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"]
    return [f for f in subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.splitlines() if f]


def scan(all_tracked: bool = False) -> list[str]:
    problems: list[str] = []
    compiled = {name: re.compile(p) for name, p in PATTERNS.items()}
    for path in _files(all_tracked):
        if any(rx.search(path) for rx in FORBIDDEN_PATHS):
            problems.append(f"{path}: runtime credential/identity file must not be committed")
            continue
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                lines = fh.readlines()
        except (IsADirectoryError, FileNotFoundError):
            continue
        for number, line in enumerate(lines, 1):
            if ALLOW_MARKER in line:
                continue
            for name, rx in compiled.items():
                if rx.search(line):
                    problems.append(f"{path}:{number}: looks like {name}")
    return problems


def main() -> int:
    problems = scan(all_tracked="--all" in sys.argv)
    for p in problems:
        print(p, file=sys.stderr)
    if problems:
        print("\nRemove the secret (use an environment variable or secret store) before committing.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
