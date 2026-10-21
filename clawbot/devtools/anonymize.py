"""
Anonymise a customer export before it leaves the store (or before it is shared beyond us).

    .venv/bin/python -m clawbot.devtools.anonymize in.csv out.csv --salt-env PILOT_SALT [--hash-skus]

- Keeps only columns on an allowlist (items, quantities, money, dates, store, supplier); any other
  column is dropped unless named with --keep. Columns about people or payment (customer, billing,
  shipping, recipient, email, phone, card / PAN, address, staff, notes, tags, device …) are always dropped.
- Replaces order / receipt / transaction IDs with a salted hash: the same ID always becomes the
  same token (so lines of one order stay together and re-imports still dedupe), but it cannot be
  reversed without the salt. The salt is read from an environment variable and never written out.
- Keeps SKUs, barcodes, quantities, prices, dates and supplier names (needed to map items and units).
  `--hash-skus` hashes SKUs and barcodes too, if the store prefers; mapping then has to be done on
  their side with the same salt.
Prints which columns were dropped / hashed / kept, for the store to check before sending.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import os
import re
import sys

# People and payment details: always dropped, even if --keep names them.
NEVER = re.compile(r"customer|buyer|client|email|e-mail|phone|mobile|card|\bpan\b|billing|shipping|recipient|address|"
                   r"street|city|zip|postal|employee|staff|cashier|server|loyalty|member|note|comment|tag|device|ip\b|"
                   r"first name|last name|full name|contact|signature", re.I)
SKU = re.compile(r"sku|barcode|upc|ean|gtin|item #|item number|product code", re.I)
# Identifiers: kept only as salted hashes (Shopify's order "Name" is an order number).
HASH = re.compile(r"^name$|order|receipt|transaction|ticket|payment id|invoice|reference|\bid\b", re.I)
# Everything else is dropped unless it is clearly about items, quantities, money, time or place of sale.
ALLOW = re.compile(r"date|time|created|sold|qty|quantity|units|count|price|cost|amount|total|subtotal|discount|tax|"
                   r"currency|item|product|variant|description|category|vendor|supplier|location|store|outlet|type|"
                   r"status|unit|pack|case|refund|return|restock|eta|expected|confirmed|po\b|po #", re.I)


def token(value: str, salt: bytes) -> str:
    return "X" + hmac.new(salt, value.strip().encode(), hashlib.sha256).hexdigest()[:16] if value.strip() else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Anonymise a sales / order export (see module docstring)")
    parser.add_argument("source")
    parser.add_argument("target")
    parser.add_argument("--salt-env", default="PILOT_SALT", help="environment variable holding the secret salt")
    parser.add_argument("--hash-skus", action="store_true")
    parser.add_argument("--keep", action="append", default=[], help="keep this column although it is not on the allowlist")
    args = parser.parse_args(argv)
    salt = os.getenv(args.salt_env)
    if not salt or len(salt) < 16:
        print(f"Set {args.salt_env} to a secret of at least 16 characters (keep it; do not send it with the file).",
              file=sys.stderr)
        return 2
    with open(args.source, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows:
        print("empty file", file=sys.stderr)
        return 2
    header = rows[0]
    plan = []
    keep = {k.strip().lower() for k in args.keep}
    for name in header:
        if NEVER.search(name):
            plan.append("drop")
        elif SKU.search(name):
            plan.append("hash" if args.hash_skus else "keep")
        elif HASH.search(name.strip()):
            plan.append("hash")
        elif ALLOW.search(name) or name.strip().lower() in keep:
            plan.append("keep")
        else:
            plan.append("drop")  # unknown column: not sent unless --keep says so
    with open(args.target, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([h for h, p in zip(header, plan) if p != "drop"])
        for row in rows[1:]:
            w.writerow([token(c, salt.encode()) if p == "hash" else c
                        for c, p in zip(row + [""] * (len(header) - len(row)), plan) if p != "drop"])
    for action in ("drop", "hash", "keep"):
        cols = [h for h, p in zip(header, plan) if p == action]
        print(f"{action:>5}: {', '.join(cols) or '—'}")
    print(f"wrote {len(rows) - 1} rows to {args.target}. Check the 'keep' list before sending.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
