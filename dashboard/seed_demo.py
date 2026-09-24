"""Seed a demo run for the dashboard (M10).

Builds one run with an executed chain, two held approvals, and a denial:
exactly the states the 90s demo walks through. CRM-only, so it works
offline. Prints the run id and nothing else sensitive.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from bench.common import boot_crm, load_dotenv_silent  # noqa: E402

from hyperion.config import load as load_config  # noqa: E402
from hyperion.executor import executor as ex  # noqa: E402
from hyperion.executor.clients import SystemClient  # noqa: E402
from hyperion.ledger import db, store  # noqa: E402

POLICY = {
    "default": "allow",
    "rules": [
        {"match": {"system": "crm", "operation": "deals.create",
                   "when": "amount_cents > 100000"},
         "effect": "require_approval"},
        {"match": {"system": "crm", "operation": "leads.delete"},
         "effect": "deny"},
    ],
}


def main() -> int:
    load_dotenv_silent(REPO_ROOT / ".env")
    conn = db.connect(load_config())
    db.migrate_up(conn)
    crm_url = os.environ.get("CRM_BASE_URL")
    if not crm_url:
        crm_url, _, _ = boot_crm()
    clients = {"crm": SystemClient(base_url=crm_url)}
    specs = ex.load_specs()
    try:
        run_id = store.create_run(conn, client="dashboard-demo")
        store.stamp_policy(
            conn, run_id,
            hashlib.sha256(json.dumps(
                POLICY, sort_keys=True,
                separators=(",", ":")).encode()).hexdigest())

        def run(op, args):
            out = ex.execute(conn, run_id, "crm", op, args,
                             specs=specs, clients=clients, policy=POLICY)
            print(f"{op:14s} -> {out['status']}")
            return out

        lead = run("leads.create", {"name": "Demo Lead"})
        lead_id = lead["produced"]["lead_id"]
        deal = run("deals.create", {"lead_id": lead_id, "title": "Starter",
                                    "amount_cents": 5000})
        run("notes.add", {"deal_id": deal["produced"]["deal_id"],
                          "body": "First call went well."})
        run("leads.update", {"lead_id": lead_id, "name": "Demo Lead (won)"})
        run("deals.create", {"lead_id": lead_id, "title": "Enterprise",
                             "amount_cents": 250000})
        run("leads.delete", {"lead_id": lead_id})
        run("emails.send", {"to": "demo@example.com", "subject": "Wrap-up",
                            "body": "Thanks for the demo."})
        print(f"\nrun {run_id}")
        print(f"open http://localhost:3000/runs/{run_id}")
        return 0
    finally:
        clients["crm"].close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
