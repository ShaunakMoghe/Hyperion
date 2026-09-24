"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from hyperion.config import load as load_config
from hyperion.executor import approvals, rollback_exec, rollback_plan
from hyperion.executor import executor as ex
from hyperion.executor.clients import SystemClient
from hyperion.ledger import db, store
from hyperion.ledger import export as audit_export


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hyperion", description="Hyperion v2 CLI")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("version", help="print version")

    ledger = sub.add_parser("ledger", help="ledger commands")
    ledger_sub = ledger.add_subparsers(dest="ledger_cmd")
    verify = ledger_sub.add_parser("verify", help="verify a run ledger chain")
    verify.add_argument("run", help="run id to verify")
    export = ledger_sub.add_parser("export", help="export a run audit artifact")
    export.add_argument("--run", required=True, help="run id to export")
    export.add_argument("--out", default=None,
                        help="write JSON here instead of stdout")

    rb = sub.add_parser("rollback", help="rollback commands")
    rb_sub = rb.add_subparsers(dest="rb_cmd")
    plan = rb_sub.add_parser("plan", help="dry-run rollback plan")
    plan.add_argument("--run", required=True)
    plan.add_argument("--target", action="append", default=[],
                      help="call id (repeatable)")
    plan.add_argument("--mode", default="provenance")
    plan.add_argument("--force", action="store_true")
    plan.add_argument("--json", action="store_true")
    run = rb_sub.add_parser("run", help="execute a rollback")
    run.add_argument("--run", required=True)
    run.add_argument("--target", action="append", default=[])
    run.add_argument("--mode", default="provenance")
    run.add_argument("--force", action="store_true")
    resume = rb_sub.add_parser("resume", help="resume an interrupted rollback")
    resume.add_argument("rollback_id")

    approve = sub.add_parser("approve", help="approve a held call and execute")
    approve.add_argument("call_id")
    approve.add_argument("--by", default="")
    deny = sub.add_parser("deny", help="deny a held call")
    deny.add_argument("call_id")
    deny.add_argument("--by", default="")
    pending = sub.add_parser("approvals",
                             help="list held calls awaiting a decision")
    pending.add_argument("--run", default=None,
                         help="only this run id (default: all runs)")
    return p


def _clients() -> dict[str, SystemClient]:
    import os

    base = os.environ.get("CRM_BASE_URL", "http://127.0.0.1:8001")
    return {"crm": SystemClient(base_url=base)}


def _valid_uuid(value: str | None) -> bool:
    if value is None:
        return True
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "version":
        print("hyperion 0.1.0")
        return 0
    if args.cmd is None:
        build_parser().print_help()
        return 2

    conn = db.connect(load_config())
    db.migrate_up(conn)
    try:
        if args.cmd == "ledger" and args.ledger_cmd == "verify":
            if not _valid_uuid(args.run):
                print(f"hyperion: {args.run!r} is not a run id",
                      file=sys.stderr)
                return 1
            result = store.verify_chain(conn, args.run)
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        if args.cmd == "ledger" and args.ledger_cmd == "export":
            if not _valid_uuid(args.run):
                print(f"hyperion: {args.run!r} is not a run id",
                      file=sys.stderr)
                return 1
            try:
                artifact = audit_export.export_run(conn, args.run)
            except KeyError as e:
                print(f"hyperion: {e}", file=sys.stderr)
                return 1
            text = json.dumps(artifact, indent=2, default=str)
            if args.out:
                Path(args.out).write_text(text, encoding="utf-8")
            else:
                print(text)
            return 0 if artifact["chain"]["ok"] else 1
        if args.cmd == "rollback" and args.rb_cmd == "plan":
            the_plan = rollback_plan.plan(conn, args.run, args.target,
                                          mode=args.mode, force=args.force)
            if args.json:
                print(json.dumps(the_plan, indent=2))
            else:
                print(rollback_plan.plan_text(the_plan))
            return 0 if the_plan["status"] == "ready" else 1
        if args.cmd == "rollback" and args.rb_cmd in ("run", "resume"):
            clients = _clients()
            try:
                specs = ex.load_specs()
                if args.rb_cmd == "run":
                    out = rollback_exec.start(
                        conn, args.run, args.target, mode=args.mode,
                        force=args.force, clients=clients, specs=specs)
                else:
                    out = rollback_exec.resume(conn, args.rollback_id,
                                               clients, specs)
                print(json.dumps(out, indent=2, default=str))
                return 0 if out["status"] == "completed" else 1
            finally:
                clients["crm"].close()
        if args.cmd == "approve":
            clients = _clients()
            try:
                out = ex.approve_and_execute(conn, args.call_id, args.by,
                                             ex.load_specs(), clients)
                print(json.dumps(out, indent=2, default=str))
                return 0 if out["status"] in ("executed",
                                              "already_executed") else 1
            finally:
                clients["crm"].close()
        if args.cmd == "deny":
            out = approvals.decide(conn, args.call_id, False, args.by)
            print(json.dumps(out, indent=2, default=str))
            return 0 if out["status"] == "denied" else 1
        if args.cmd == "approvals":
            if not _valid_uuid(args.run):
                print(f"hyperion: {args.run!r} is not a run id",
                      file=sys.stderr)
                return 1
            pending = approvals.list_pending(conn, args.run)
            print(json.dumps(pending, indent=2, default=str))
            return 0
    finally:
        conn.close()
    build_parser().print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
