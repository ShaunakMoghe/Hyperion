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


class _StubClient:
    """Scripted client: (method, path) -> (code, body), exception, or a
    list of those consumed in order across repeated calls."""

    def __init__(self, script):
        self.script = script

    def request(self, method, path_template, args):
        action = self.script[(method, path_template)]
        if isinstance(action, list):
            action = action.pop(0)
        if isinstance(action, Exception):
            raise action
        return action


def _widget_spec(**overrides):
    spec = {
        "spec_version": 1,
        "id": "stub.widgets.create",
        "system": "stub",
        "operation": {"method": "POST", "path": "/widgets"},
        "effect_class": "reversible",
        "fidelity": "exact",
        "before_image": None,
        "produces": [{"name": "widget_id", "from": "$.response.id"}],
        "inverse": {
            "operation": {"method": "DELETE",
                          "path": "/widgets/{id}"},
            "params": {"id": "$.produced.widget_id"},
            "body_from_before_image": [],
        },
        "verify": {
            "read": {"method": "GET", "path": "/widgets",
                     "params": {"id": "$.produced.widget_id"}},
            "compare": {"fields": ["id"], "against": "response"},
        },
        "provenance": {},
    }
    spec.update(overrides)
    return spec


def _run_stub(env, spec, script, args=None, **kw):
    conn, run_id = env["conn"], env["run_id"]
    return executor.execute(
        conn, run_id, "stub", "widgets.create",
        {"name": "w"} if args is None else args,
        specs={"stub.widgets.create": spec},
        clients={"stub": _StubClient(script)}, **kw)


def test_verify_error_body_not_stored_as_post_image(env):
    # The forward effect stands (it happened); the error body must not be
    # recorded as post state, so drift checks skip the missing post-image
    # instead of comparing against garbage.
    out = _run_stub(env, _widget_spec(), {
        ("POST", "/widgets"): (201, {"id": "widget-1"}),
        ("GET", "/widgets"): (500, {"error": "boom"}),
    })
    assert out["status"] == "executed"
    row = store.get_call(env["conn"], out["call_id"])
    assert row["post_image"] is None


def _updating_spec(**overrides):
    spec = _widget_spec(
        before_image={"read": {"method": "GET", "path": "/widgets",
                               "params": {"id": "$.args.id"}},
                      "fields": ["name"]},
        produces=[],
        verify={"read": {"method": "GET", "path": "/widgets",
                         "params": {"id": "$.args.id"}},
                "compare": {"fields": ["name"], "against": "before_image"}},
    )
    spec.update(overrides)
    return spec


def test_before_image_spec_stores_field_subset(env):
    # Drift baseline for before_image specs is the field subset, matching
    # what rollback recomputes (shared projection, no false conflicts).
    row_body = {"id": "widget-1", "name": "w", "extra": True}
    out = _run_stub(env, _updating_spec(), {
        ("GET", "/widgets"): [(200, dict(row_body)), (200, dict(row_body))],
        ("POST", "/widgets"): (200, dict(row_body)),
    }, args={"id": "widget-1", "name": "w"})
    assert out["status"] == "executed"
    row = store.get_call(env["conn"], out["call_id"])
    assert row["before_image"] == {"name": "w"}
    assert row["post_image"] == {"name": "w"}


def test_tombstone_verify_projects_to_no_post_image(env):
    # A 410 tombstone read is a legitimate post-state: the effect stands
    # with no post-image rather than failing the forward call.
    out = _run_stub(env, _updating_spec(), {
        ("GET", "/widgets"): [(200, {"id": "widget-1", "name": "w"}),
                              (410, {"detail": {"deleted": True}})],
        ("POST", "/widgets"): (200, {"id": "widget-1"}),
    }, args={"id": "widget-1", "name": "w"})
    assert out["status"] == "executed"
    row = store.get_call(env["conn"], out["call_id"])
    assert row["post_image"] is None


def test_verify_runs_without_produces(env):
    spec = _widget_spec(
        produces=[],
        verify={"read": {"method": "GET", "path": "/widgets",
                         "params": {"name": "$.args.name"}},
                "compare": {"fields": ["name"], "against": "response"}},
    )
    out = _run_stub(env, spec, {
        ("POST", "/widgets"): (201, {"id": "widget-1"}),
        ("GET", "/widgets"): (200, {"id": "widget-1", "name": "w"}),
    })
    assert out["status"] == "executed"
    row = store.get_call(env["conn"], out["call_id"])
    assert row["post_image"] == {"id": "widget-1", "name": "w"}


def test_verify_unresolvable_params_fails_call(env):
    spec = _widget_spec(produces=[])  # verify refs $.produced: unresolvable
    out = _run_stub(env, spec, {
        ("POST", "/widgets"): (201, {"id": "widget-1"}),
    })
    assert out["status"] == "failed"
    assert "verify params unresolvable" in out["reason"]


def test_verify_transport_error_recorded_not_raised(env):
    out = _run_stub(env, _widget_spec(), {
        ("POST", "/widgets"): (201, {"id": "widget-1"}),
        ("GET", "/widgets"): ConnectionError("down"),
    })
    assert out["status"] == "failed"
    assert "verify read failed" in out["reason"]
    assert "ConnectionError" in out["reason"]
    assert store.get_call(env["conn"], out["call_id"])["status"] == "failed"


def test_before_image_transport_error_recorded_not_raised(env):
    spec = _widget_spec(
        before_image={"read": {"method": "GET", "path": "/widgets",
                               "params": {"name": "$.args.name"}},
                      "fields": ["name"]},
        verify=None,
    )
    out = _run_stub(env, spec, {
        ("GET", "/widgets"): ConnectionError("down"),
        ("POST", "/widgets"): (201, {"id": "widget-1"}),
    })
    assert out["status"] == "failed"
    assert "before-image read failed" in out["reason"]


def test_malformed_policy_dict_denied_not_raised(env):
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    for bad in ({"rules": "nope"}, {"default": "bogus", "rules": []},
                {"default": "allow", "rules": [{"match": {"system": "s"}}]}):
        out = executor.execute(conn, run_id, "crm", "leads.create",
                               {"name": "P"}, specs=specs, clients=clients,
                               policy=bad)
        assert out["status"] == "denied"
        assert "invalid policy dict" in out["reason"]
        assert store.get_call(conn, out["call_id"])["status"] == "blocked"


@pytest.mark.parametrize("args", [0, "", [], "x", False])
def test_non_dict_args_denied_not_raised(env, args):
    conn, run_id, clients, specs = (env["conn"], env["run_id"],
                                    env["clients"], env["specs"])
    out = executor.execute(conn, run_id, "crm", "leads.create", args,
                           specs=specs, clients=clients)
    assert out["status"] == "denied"
    assert "malformed args" in out["reason"]


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
