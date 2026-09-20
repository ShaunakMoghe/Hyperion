"""H-041: gateway routing is pure and explicit (no processes)."""

from hyperion.mcp_gateway import proxy

MAP = {"unknown": "deny",
       "tools": {"crm_create_lead": {"system": "crm",
                                     "operation": "leads.create"}}}


def test_intercept_mapped_call():
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": "crm_create_lead", "arguments": {"name": "A"}}}
    assert proxy.decide_action(msg, MAP) == (
        "intercept", {"name": "crm_create_lead", "args": {"name": "A"}})


def test_forward_list_and_notifications():
    assert proxy.decide_action(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        MAP) == ("forward", {})
    assert proxy.decide_action(
        {"jsonrpc": "2.0", "method": "notifications/cancelled",
         "params": {}}, MAP) == ("forward", {})


def test_unmapped_denied_by_default():
    msg = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
           "params": {"name": "evil", "arguments": {}}}
    assert proxy.decide_action(msg, MAP)[0] == "intercept_unmapped"


def test_unmapped_forwarded_when_allow_logged():
    loose = dict(MAP, unknown="allow_logged")
    msg = {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
           "params": {"name": "evil", "arguments": {}}}
    assert proxy.decide_action(msg, loose) == ("forward", {})


def test_format_result_shapes():
    ok = proxy.format_result(1, {"status": "executed", "call_id": "c",
                                 "response": {"id": "x"}, "produced": {}})
    assert ok["id"] == 1 and "isError" not in ok["result"]
    held = proxy.format_result(2, {"status": "held", "call_id": "c",
                                   "reason": "r"})
    assert "PENDING_APPROVAL" in held["result"]["content"][0]["text"]
    assert "isError" not in held["result"]
    bad = proxy.format_result(3, {"status": "denied", "reason": "nope"})
    assert bad["result"]["isError"] is True
    denied = proxy.format_denied(4, "nope")
    assert denied["error"]["code"] == -32000
