"""M7: verifier covers the CRM holdout path (live CRM, no Stripe).

The hand-written notes.add spec must verify exact, and the trial must
leave no live residue (fixtures tombstoned, note hard-deleted).
"""

from pathlib import Path

import pytest

from hyperion.specs import loader
from hyperion.synth import verifier

pytestmark = pytest.mark.integration


def test_hand_notes_add_verifies_exact(env):
    conn, clients = env["conn"], env["clients"]
    specs = loader.load_dir(
        Path(__file__).resolve().parents[2] / "specs" / "crm")
    _, pre = clients["crm"].request("GET", "/snapshot", {})
    result = verifier.verify_spec(clients["crm"], specs["crm.notes.add"],
                                  conn, model="human", trials=1)
    assert result["outcome"] == "verified_exact", result
    _, post = clients["crm"].request("GET", "/snapshot", {})
    live_leftovers = []
    for table, rows in post.items():
        if table == "emails_outbox":
            continue
        before = {r["id"] for r in pre.get(table, [])}
        for row in rows:
            if row["id"] not in before and row.get("deleted_at") is None:
                live_leftovers.append(f"{table}:{row['id']}")
    assert live_leftovers == []
