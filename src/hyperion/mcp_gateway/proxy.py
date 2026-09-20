"""MCP stdio proxy (H-041): frame relay with tools/call interception.

Byte-transparent for everything except mapped `tools/call` requests, which
run through the spec executor. Unmapped tools follow the unknown-operation
policy. stdio framing is newline-delimited JSON-RPC (see ADR 003).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import yaml

from hyperion.config import load as load_config
from hyperion.executor import approvals
from hyperion.executor import executor as ex
from hyperion.executor.clients import SystemClient
from hyperion.ledger import db, store

REPO_ROOT = Path(__file__).resolve().parents[3]


def default_map_path() -> Path:
    override = os.environ.get("HYPERION_TOOL_MAP")
    if override:
        return Path(override)
    return REPO_ROOT / "gateway" / "tool_map.yaml"


def load_map(path: Path | None = None) -> dict:
    path = path or default_map_path()
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def decide_action(message: Any, tool_map: dict) -> tuple[str, dict]:
    """Pure routing: ('intercept', {name, args}) or ('forward', {})."""
    if not isinstance(message, dict) or message.get("method") != "tools/call":
        return "forward", {}
    params = message.get("params") or {}
    name = params.get("name")
    if name not in tool_map.get("tools", {}):
        policy = tool_map.get("unknown", "deny")
        if policy == "allow_logged":
            return "forward", {}
        return "intercept_unmapped", {"name": name}
    return "intercept", {"name": name, "args": params.get("arguments") or {}}


def format_result(request_id: Any, result: dict) -> dict:
    """Map an executor result to a JSON-RPC tools/call response."""
    status = result.get("status")
    if status == "executed":
        payload = {"call_id": result["call_id"],
                   "response": result.get("response"),
                   "produced": result.get("produced", {})}
        return {"jsonrpc": "2.0", "id": request_id,
                "result": {"content": [{"type": "text",
                                        "text": json.dumps(payload)}]}}
    if status == "held":
        payload = {"result": approvals.PENDING, "call_id": result["call_id"],
                   "reason": result.get("reason", "")}
        return {"jsonrpc": "2.0", "id": request_id,
                "result": {"content": [{"type": "text",
                                        "text": json.dumps(payload)}]}}
    text = json.dumps({"status": status,
                       "reason": result.get("reason", "")})
    return {"jsonrpc": "2.0", "id": request_id,
            "result": {"content": [{"type": "text", "text": text}],
                       "isError": True}}


def format_denied(request_id: Any, reason: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": -32000, "message": f"hyperion denied: {reason}"}}


class Gateway:
    def __init__(self, tool_map: dict, conn, run_id: str,
                 specs: dict, clients: dict[str, SystemClient]) -> None:
        self.map = tool_map
        self.conn = conn
        self.run_id = run_id
        self.specs = specs
        self.clients = clients
        self._write_lock = threading.Lock()
        self._upstream: subprocess.Popen | None = None

    def _write_downstream(self, obj: Any) -> None:
        line = json.dumps(obj, separators=(",", ":"))
        with self._write_lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()

    def handle_message(self, message: Any) -> Any:
        """Route one downstream message. Returns the response object, a list
        of responses (batch), or None (forwarded / notification)."""
        if isinstance(message, list):
            responses = []
            for element in message:
                resp = self.handle_message(element)
                if resp is not None:
                    responses.append(resp)
            return responses or None
        action, info = decide_action(message, self.map)
        if action == "forward":
            return None
        request_id = message.get("id")
        if request_id is None:
            return None  # notification shaped like a call: forward instead
        if action == "intercept_unmapped":
            result = ex.execute(
                self.conn, self.run_id, "mcp", str(info["name"]), {},
                specs=self.specs, clients=self.clients,
                unknown=self.map.get("unknown", "deny"),
            )
            if result["status"] == "held":
                return format_result(request_id, result)
            return format_denied(request_id, result.get("reason", "denied"))
        mapping = self.map["tools"][info["name"]]
        args = dict(info["args"])
        depends_on = args.pop("depends_on", None)
        result = ex.execute(
            self.conn, self.run_id, mapping["system"], mapping["operation"],
            args, specs=self.specs, clients=self.clients,
            unknown=self.map.get("unknown", "deny"),
            declared_deps=depends_on if isinstance(depends_on, list) else None,
        )
        return format_result(request_id, result)

    def _pump_downstream(self) -> None:
        assert self._upstream and self._upstream.stdin
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                continue  # fail-closed: drop malformed input, stay up
            response = self.handle_message(message)
            if response is not None:
                self._write_downstream(response)
            else:
                try:
                    self._upstream.stdin.write(line + "\n")
                    self._upstream.stdin.flush()
                except BrokenPipeError:
                    break

    def _pump_upstream(self) -> None:
        assert self._upstream and self._upstream.stdout
        for line in self._upstream.stdout:
            with self._write_lock:
                sys.stdout.write(line)
                sys.stdout.flush()

    def run(self) -> int:
        upstream_cfg = self.map.get("upstream", {})
        command = upstream_cfg.get("command")
        if not command:
            print("gateway: no upstream.command in tool map", file=sys.stderr)
            return 2
        # "python" means this interpreter: the upstream needs the same
        # project environment (SDK, deps), which PATH may not provide.
        if command[0] == "python":
            command = [sys.executable, *command[1:]]
        self._upstream = subprocess.Popen(
            command,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True, bufsize=1,
            cwd=upstream_cfg.get("cwd") or str(REPO_ROOT),
            env={**os.environ, **upstream_cfg.get("env", {})},
        )
        worker = threading.Thread(target=self._pump_upstream, daemon=True)
        worker.start()
        try:
            self._pump_downstream()
        finally:
            assert self._upstream
            self._upstream.terminate()
            try:
                self._upstream.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._upstream.kill()
        return 0


def main() -> int:
    tool_map = load_map()
    cfg = load_config()
    conn = db.connect(cfg)
    db.migrate_up(conn)
    run_id = os.environ.get("HYPERION_RUN_ID")
    if run_id:
        row = conn.execute("SELECT id FROM runs WHERE id = %s",
                           (run_id,)).fetchone()
        if row is None:
            print(f"gateway: HYPERION_RUN_ID {run_id} not found",
                  file=sys.stderr)
            return 2
    else:
        run_id = store.create_run(
            conn, client=tool_map.get("session", {}).get("client", "mcp"))
    specs = ex.load_specs()
    crm_base = os.environ.get("CRM_BASE_URL", "http://127.0.0.1:8001")
    clients: dict[str, SystemClient] = {"crm": SystemClient(base_url=crm_base)}
    try:
        return Gateway(tool_map, conn, run_id, specs, clients).run()
    finally:
        clients["crm"].close()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
