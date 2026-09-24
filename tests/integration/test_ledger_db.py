"""H-010: migrations apply/rollback cleanly; runs and calls persist (real Postgres)."""

import json

import pytest

from hyperion.config import load
from hyperion.ledger import db, store

pytestmark = pytest.mark.integration


def _conn():
    conn = db.connect(load())
    db.migrate_up(conn)
    return conn


def test_migrations_round_trip():
    conn = db.connect(load())
    try:
        db.migrate_down(conn)  # normalize: start from a clean slate
        assert db.applied_versions(conn) == []
        assert db.migrate_up(conn) == [1, 2]
        assert db.applied_versions(conn) == [1, 2]
        assert db.migrate_down(conn) == [2, 1]
        assert db.applied_versions(conn) == []
        assert db.migrate_up(conn) == [1, 2]
    finally:
        conn.close()


def test_run_and_chained_calls_verify():
    conn = _conn()
    try:
        run_id = store.create_run(conn, client="test", meta={"case": "chain"})
        c1 = store.append_call(
            conn, run_id, system="crm", operation="leads.create",
            args={"name": "Ada"}, effect_class="reversible",
            fidelity_expected="exact",
        )
        c2 = store.append_call(
            conn, run_id, system="crm", operation="deals.create",
            args={"title": "Big"}, effect_class="reversible",
            fidelity_expected="exact",
        )
        assert c1["seq"] == 0 and c2["seq"] == 1
        assert c2["prev_hash"] == c1["entry_hash"]
        result = store.verify_chain(conn, run_id)
        assert result == {"ok": True, "calls": 2}
    finally:
        conn.close()


def test_tamper_detected_with_first_broken_entry():
    conn = _conn()
    try:
        run_id = store.create_run(conn, client="test")
        c1 = store.append_call(
            conn, run_id, system="crm", operation="leads.create",
            args={"name": "Ada"}, effect_class="reversible",
            fidelity_expected="exact",
        )
        c2 = store.append_call(
            conn, run_id, system="crm", operation="leads.create",
            args={"name": "Bob"}, effect_class="reversible",
            fidelity_expected="exact",
        )
        conn.execute(
            "UPDATE calls SET args = %s WHERE id = %s",
            (json.dumps({"name": "Mallory"}), c1["id"]),
        )
        result = store.verify_chain(conn, run_id)
        assert result["ok"] is False
        assert result["first_broken_call_id"] == str(c1["id"])
        # The untampered later entry still chains off the stored (tampered)
        # prev link, so the FIRST broken entry is the tampered one.
        assert str(c2["id"]) != result["first_broken_call_id"]
    finally:
        conn.close()


def test_idempotent_append_returns_original():
    conn = _conn()
    try:
        run_id = store.create_run(conn, client="test")
        first = store.append_call(
            conn, run_id, system="crm", operation="leads.create",
            args={"name": "Ada"}, effect_class="reversible",
            fidelity_expected="exact", idempotency_key="idem-1",
        )
        second = store.append_call(
            conn, run_id, system="crm", operation="leads.create",
            args={"name": "OTHER"}, effect_class="reversible",
            fidelity_expected="exact", idempotency_key="idem-1",
        )
        assert str(first["id"]) == str(second["id"])
        assert store.verify_chain(conn, run_id)["calls"] == 1
    finally:
        conn.close()
