"""
Unified CLI entrypoint for the PriceScout + Trend Analyst platform.

Usage:
    python cli.py price     <subcommand>    # PriceScout agent commands
    python cli.py trend     <subcommand>    # Trend Analyst agent commands
    python cli.py imsg      <subcommand>    # iMessage digest commands
    python cli.py procure   <subcommand>    # Procurement agent commands
    python cli.py inventory <subcommand>    # Inventory agent commands

Or run each CLI directly:
    python price_cli.py       <subcommand>
    python trend_cli.py       <subcommand>
    python imsg_cli.py        <subcommand>
    python procurement_cli.py <subcommand>
    python inventory_cli.py   <subcommand>
"""

from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    agent = sys.argv[1].lower()
    # Shift argv so the sub-CLI sees its own subcommands
    sys.argv = [sys.argv[0]] + sys.argv[2:]

    if agent == "price":
        from price_cli import build_parser
        parser = build_parser()
        args = parser.parse_args()
        args.func(args)

    elif agent == "trend":
        from trend_cli import run, build_parser
        parser = build_parser()
        args = parser.parse_args()
        run(args.business, args.location, args.categories,
            args.lookback, args.url, getattr(args, "show_sources", False))

    elif agent == "imsg":
        from imsg_cli import build_parser
        parser = build_parser()
        args = parser.parse_args()
        args.func(args)

    elif agent == "procure":
        from procurement_cli import build_parser
        parser = build_parser()
        args = parser.parse_args()
        args.func(args)

    elif agent == "inventory":
        from inventory_cli import build_parser
        parser = build_parser()
        args = parser.parse_args()
        args.func(args)

    elif agent == "onboard":
        from onboarding_cli import build_parser, main
        main()

    else:
        print(f"Unknown agent '{agent}'. Choose: price, trend, imsg, procure, inventory, onboard")
        sys.exit(1)


if __name__ == "__main__":
    main()
