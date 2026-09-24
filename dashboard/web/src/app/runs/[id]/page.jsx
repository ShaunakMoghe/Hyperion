"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useMemo, useState } from "react";
import GraphCanvas from "../../components/GraphCanvas";
import { API_BASE, api, shortId, useRunEvents } from "../../../lib/api";

const RESTORED = new Set(["restored_exact", "restored_equivalent", "compensated"]);

function StatusPill({ status }) {
  const color =
    status === "executed"
      ? "text-[var(--ok)] border-white/10"
      : status === "held"
        ? "text-[var(--wait)] border-white/10"
        : "text-[var(--bad)] border-white/10";
  return (
    <span className={`mono text-[10px] uppercase tracking-widest border px-2 py-0.5 ${color}`}>
      {status}
    </span>
  );
}

function Kv({ label, value }) {
  return (
    <div className="flex gap-3 py-1">
      <span className="micro-label w-28 shrink-0 pt-px">{label}</span>
      <span className="mono text-xs text-[var(--ink-dim)] break-all">{value}</span>
    </div>
  );
}

function NodePanel({ call, onRollbackOne, busy }) {
  if (!call) {
    return (
      <div className="panel p-5">
        <p className="micro-label">call detail</p>
        <p className="text-sm text-[var(--ink-dim)] mt-3">
          Select a node in the graph.
        </p>
      </div>
    );
  }
  return (
    <div className="panel p-5">
      <div className="flex items-center justify-between gap-3">
        <p className="micro-label">call #{call.seq}</p>
        <StatusPill status={call.status} />
      </div>
      <h2 className="mono text-sm mt-3 break-all">
        {call.system}.{call.operation}
      </h2>
      <div className="mt-3 border-t border-[var(--line)] pt-3">
        <Kv label="call id" value={shortId(call.call_id)} />
        <Kv label="effect" value={call.effect_class} />
        {call.decision_reason && <Kv label="reason" value={call.decision_reason} />}
        {call.spec_id && <Kv label="spec" value={call.spec_id} />}
      </div>
      <div className="mt-3 border-t border-[var(--line)] pt-3">
        <p className="micro-label mb-2">args</p>
        <pre className="mono text-xs text-[var(--ink-dim)] whitespace-pre-wrap break-all">
          {JSON.stringify(call.args, null, 2)}
        </pre>
      </div>
      {call.status === "executed" && (
        <button
          disabled={busy}
          onClick={() => onRollbackOne(call.call_id)}
          className="mono text-xs mt-4 w-full border border-[var(--line)] px-3 py-2 hover:border-white/40 disabled:opacity-40 transition-colors"
        >
          {busy ? "working…" : "roll back from here"}
        </button>
      )}
    </div>
  );
}

export default function RunDetailPage({ params }) {
  const { id: runId } = use(params);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    api(`/api/runs/${runId}`)
      .then((body) => {
        setDetail(body);
        setError(null);
      })
      .catch((e) => setError(String(e)));
  }, [runId]);

  const [liveSnapshot, live] = useRunEvents(
    runId,
    detail ? { calls: detail.calls, edges: detail.edges, approvals: detail.approvals, rollbacks: detail.rollbacks } : null
  );
  const snapshot = liveSnapshot || (detail && {
    calls: detail.calls,
    edges: detail.edges,
    approvals: detail.approvals,
    rollbacks: detail.rollbacks,
  });

  const rolledBackIds = useMemo(() => {
    const ids = new Set();
    for (const rb of snapshot?.rollbacks || []) {
      for (const step of rb.steps || []) {
        if (RESTORED.has(step.outcome)) ids.add(step.call_id);
      }
    }
    return ids;
  }, [snapshot]);

  const calls = useMemo(
    () =>
      (snapshot?.calls || []).map((c) => ({
        ...c,
        rolledBack: rolledBackIds.has(c.call_id),
      })),
    [snapshot, rolledBackIds]
  );

  const pending = useMemo(
    () => (snapshot?.approvals || []).filter((a) => a.status === "pending"),
    [snapshot]
  );
  const callById = useMemo(
    () => Object.fromEntries(calls.map((c) => [c.call_id, c])),
    [calls]
  );

  const doRollback = useCallback(
    async (targets) => {
      setBusy(true);
      setNotice(null);
      try {
        const result = await api(`/api/runs/${runId}/rollback`, {
          method: "POST",
          body: JSON.stringify({ targets }),
        });
        const steps = (result.steps || []).map(
          (s) => `${shortId(s.call_id)}: ${s.outcome || s.status}`
        );
        setNotice(
          result.status === "completed"
            ? `rollback completed — ${steps.join(" · ") || "nothing to undo"}`
            : `rollback ${result.status}`
        );
      } catch (e) {
        setNotice(`rollback failed: ${e}`);
      } finally {
        setBusy(false);
      }
    },
    [runId]
  );

  const decide = useCallback(
    async (callId, action) => {
      setBusy(true);
      setNotice(null);
      try {
        const result = await api(`/api/approvals/${callId}/${action}`, {
          method: "POST",
          body: JSON.stringify({ by: "dashboard" }),
        });
        setNotice(`${action}d ${shortId(callId)} → ${result.status}`);
      } catch (e) {
        setNotice(`${action} failed: ${e}`);
      } finally {
        setBusy(false);
      }
    },
    []
  );

  if (error) {
    return (
      <main className="max-w-6xl mx-auto px-6 py-10">
        <Link href="/" className="mono text-xs text-[var(--ink-dim)] hover:text-white">
          ← runs
        </Link>
        <div className="panel mt-6 p-4 mono text-xs text-[var(--bad)]">{error}</div>
      </main>
    );
  }
  if (!detail || !snapshot) {
    return (
      <main className="max-w-6xl mx-auto px-6 py-10">
        <div className="mono text-xs text-[var(--ink-faint)]">loading run…</div>
      </main>
    );
  }

  const policySha = detail.run.meta?.policy_sha256;
  return (
    <main className="max-w-6xl mx-auto px-6 py-10">
      <div className="flex items-baseline justify-between">
        <Link href="/" className="mono text-xs text-[var(--ink-dim)] hover:text-white">
          ← runs
        </Link>
        <span className="mono text-[10px] uppercase tracking-widest text-[var(--ink-faint)]">
          <span style={{ color: live ? "var(--ok)" : "var(--ink-faint)" }}>●</span>{" "}
          {live ? "live" : "connecting…"}
        </span>
      </div>

      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-[var(--line)] pb-5 mt-2">
        <div>
          <h1 className="mono text-xl tracking-tight">{shortId(detail.run.id)}</h1>
          <p className="micro-label mt-2">
            {detail.run.client || "no client"} · {calls.length} calls
            {policySha && ` · policy ${policySha.slice(0, 8)}`}
          </p>
        </div>
        <div className="flex gap-2">
          <a
            href={`${API_BASE}/api/runs/${runId}/export`}
            download={`hyperion-audit-${shortId(runId)}.json`}
            className="mono text-xs text-[var(--ink-dim)] border border-[var(--line)] px-3 py-1.5 hover:text-white hover:border-white/30 transition-colors"
          >
            export audit json
          </a>
          <button
            disabled={busy}
            onClick={() => {
              if (!confirming) {
                setConfirming(true);
                setTimeout(() => setConfirming(false), 5000);
                return;
              }
              setConfirming(false);
              doRollback([]);
            }}
            className="mono text-xs bg-white text-black px-4 py-1.5 hover:bg-white/85 disabled:opacity-40 transition-colors"
          >
            {busy ? "working…" : confirming ? "confirm whole-run rollback" : "roll back run"}
          </button>
        </div>
      </header>

      {notice && (
        <div className="panel mt-4 p-3 mono text-xs text-[var(--ink-dim)]">{notice}</div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mt-4">
        <div className="lg:col-span-2 panel">
          <div className="flex items-center justify-between px-4 py-2 border-b border-[var(--line)]">
            <p className="micro-label">execution graph</p>
            <p className="mono text-[10px] text-[var(--ink-faint)]">
              solid = provenance · dashed = sequence
            </p>
          </div>
          <GraphCanvas
            calls={calls}
            edges={snapshot.edges}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
        </div>

        <div className="flex flex-col gap-4">
          <NodePanel
            call={selectedId ? callById[selectedId] : null}
            onRollbackOne={(callId) => doRollback([callId])}
            busy={busy}
          />

          <div className="panel p-5">
            <p className="micro-label">approvals · {pending.length} pending</p>
            {pending.length === 0 && (
              <p className="text-sm text-[var(--ink-dim)] mt-3">Queue empty.</p>
            )}
            {pending.map((a) => {
              const call = callById[a.call_id];
              return (
                <div key={a.call_id} className="border-t border-[var(--line)] mt-3 pt-3 first:border-0 first:mt-0 first:pt-0">
                  <p className="mono text-xs break-all">
                    {call ? `${call.system}.${call.operation}` : shortId(a.call_id)}
                  </p>
                  {call?.decision_reason && (
                    <p className="mono text-[11px] text-[var(--ink-faint)] mt-1 break-all">
                      {call.decision_reason}
                    </p>
                  )}
                  <div className="flex gap-2 mt-2">
                    <button
                      disabled={busy}
                      onClick={() => decide(a.call_id, "approve")}
                      className="mono text-xs flex-1 border border-[var(--line)] px-3 py-1.5 hover:border-white/40 disabled:opacity-40 transition-colors"
                    >
                      approve
                    </button>
                    <button
                      disabled={busy}
                      onClick={() => decide(a.call_id, "deny")}
                      className="mono text-xs flex-1 border border-[var(--line)] px-3 py-1.5 hover:border-white/40 disabled:opacity-40 transition-colors"
                    >
                      deny
                    </button>
                  </div>
                </div>
              );
            })}
          </div>

          {(snapshot.rollbacks || []).length > 0 && (
            <div className="panel p-5">
              <p className="micro-label">rollbacks</p>
              {(snapshot.rollbacks || []).map((rb) => (
                <div key={rb.id} className="border-t border-[var(--line)] mt-3 pt-3 first:border-0">
                  <div className="flex items-center justify-between">
                    <span className="mono text-xs">{shortId(rb.id)}</span>
                    <StatusPill status={rb.status} />
                  </div>
                  <div className="mt-2 flex flex-col gap-1">
                    {(rb.steps || []).map((s) => (
                      <p key={s.call_id} className="mono text-[11px] text-[var(--ink-dim)]">
                        {shortId(s.call_id)} → {s.outcome || s.status}
                      </p>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
