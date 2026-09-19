"""H-020/H-021: executor + hold queue against the live CRM (no mocks)."""

import uuid

import pytest

from hyperion.executor import approvals, executor
from hyperion.ledger import store


def _addr(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"

pytestmark = pytest.mark.integration


def test_create_lead_then_deal_records_responses_and_ids(env):
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    lead = executor.execute(conn, run_id, "crm", "leads.create",
                            {"name": "Acme"}, specs=specs, clients=clients)
    assert lead["status"] == "executed"
    lead_id = lead["produced"]["lead_id"]
    assert lead["response"]["id"] == lead_id

    deal = executor.execute(
        conn, run_id, "crm", "deals.create",
        {"lead_id": lead_id, "title": "Big", "amount_cents": 100},
        specs=specs, clients=clients,
        declared_deps=[lead["call_id"]],
    )
    assert deal["status"] == "executed"
    assert deal["response"]["lead_id"] == lead_id

    row = store.get_call(conn, deal["call_id"])
    assert row["response"]["id"] == deal["produced"]["deal_id"]
    assert row["before_image"] is None  # create-style: nothing before
    assert row["post_image"]["id"] == deal["produced"]["deal_id"]


def test_failed_forward_is_recorded_not_raised(env):
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    out = executor.execute(
        conn, run_id, "crm", "deals.create",
        {"lead_id": "00000000-0000-0000-0000-000000000000", "title": "Bad"},
        specs=specs, clients=clients,
    )
    assert out["status"] == "failed"
    assert store.get_call(conn, out["call_id"])["status"] == "failed"


def test_unknown_operation_denied_by_default(env):
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    out = executor.execute(conn, run_id, "crm", "nope.delete", {"id": "x"},
                           specs=specs, clients=clients)
    assert out["status"] == "denied"
    assert store.get_call(conn, out["call_id"])["status"] == "blocked"


def test_unknown_operation_hold_returns_pending(env):
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    out = executor.execute(conn, run_id, "crm", "nope.delete", {"id": "x"},
                           specs=specs, clients=clients, unknown="hold")
    assert out["status"] == "held"
    assert out["result"] == approvals.PENDING


def test_allow_logged_explicit_path_is_marked_unprotected(env):
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    out = executor.execute(conn, run_id, "crm", "GET /snapshot", {},
                           specs=specs, clients=clients,
                           unknown="allow_logged")
    assert out["status"] == "executed"
    assert "unprotected" in out["reason"]
    row = store.get_call(conn, out["call_id"])
    assert row["effect_class"] == "unknown"


def test_irreversible_email_held_not_sent(env):
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    to = _addr("held")
    out = executor.execute(
        conn, run_id, "crm", "emails.send",
        {"to": to, "subject": "S", "body": "B"},
        specs=specs, clients=clients,
    )
    assert out["status"] == "held"
    assert out["result"] == approvals.PENDING
    snap = clients["crm"].request("GET", "/snapshot", {})[1]["emails_outbox"]
    assert [e for e in snap if e["to_addr"] == to] == []


def test_approve_sends_once_double_approve_safe(env):
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    before = clients["crm"].request("GET", "/snapshot", {})[1]["emails_outbox"]
    to = _addr("once")
    out = executor.execute(
        conn, run_id, "crm", "emails.send",
        {"to": to, "subject": "S", "body": "B"},
        specs=specs, clients=clients,
    )
    first = executor.approve_and_execute(conn, out["call_id"], "tester",
                                         specs, clients)
    assert first["status"] == "executed"
    second = executor.approve_and_execute(conn, out["call_id"], "tester",
                                          specs, clients)
    assert second["status"] == "already_executed"
    after = clients["crm"].request("GET", "/snapshot", {})[1]["emails_outbox"]
    assert [e for e in after if e["to_addr"] == to] != []
    assert len(after) == len(before) + 1


def test_deny_blocks_without_sending(env):
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    to = _addr("never")
    out = executor.execute(
        conn, run_id, "crm", "emails.send",
        {"to": to, "subject": "S", "body": "B"},
        specs=specs, clients=clients,
    )
    decision = approvals.decide(conn, out["call_id"], False, "tester")
    assert decision["status"] == "denied"
    snap = clients["crm"].request("GET", "/snapshot", {})[1]["emails_outbox"]
    assert [e for e in snap if e["to_addr"] == to] == []
