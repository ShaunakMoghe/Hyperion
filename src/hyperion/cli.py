"""Command line entry point (H-012 will grow `ledger verify`)."""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hyperion", description="Hyperion v2 CLI")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("version", help="print version")
    ledger = sub.add_parser("ledger", help="ledger commands")
    ledger_sub = ledger.add_subparsers(dest="ledger_cmd")
    verify = ledger_sub.add_parser("verify", help="verify a run ledger chain")
    verify.add_argument("run", help="run id to verify")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "version":
        print("hyperion 0.1.0")
        return 0
    if args.cmd == "ledger" and args.ledger_cmd == "verify":
        print("ledger verify is not implemented until H-012", file=sys.stderr)
        return 2
    build_parser().print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
