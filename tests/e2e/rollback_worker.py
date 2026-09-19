"""Worker subprocess for the crash-resume test.

Persists a rollback, prints its id, then drives it with a slow pre-inverse
hook (sleep, no I/O). The parent kills this process mid-step and resumes
in-process. Real DB, real CRM; nothing is mocked.
"""

import argparse
import json
import os
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--targets", required=True, help="comma-separated call ids")
    parser.add_argument("--crm", required=True)
    args = parser.parse_args()

    from hyperion.config import load
    from hyperion.executor import executor as ex
    from hyperion.executor import rollback_exec
    from hyperion.executor.clients import SystemClient
    from hyperion.ledger import db

    sleep_s = float(os.environ.get("ROLLBACK_HOOK_SLEEP", "15"))

    def slow_hook(step, call, spec):
        time.sleep(sleep_s)

    conn = db.connect(load())
    clients = {"crm": SystemClient(base_url=args.crm)}
    try:
        rollback_id = rollback_exec.persist(conn, args.run,
                                            args.targets.split(","))
        print(json.dumps({"rollback_id": rollback_id}), flush=True)
        rollback_exec.resume(conn, rollback_id, clients, ex.load_specs(),
                             slow_hook)
    finally:
        clients["crm"].close()
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
