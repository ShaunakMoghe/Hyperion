"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, shortId } from "../lib/api";

function StatusCounts({ byStatus }) {
  const entries = Object.entries(byStatus || {});
  if (entries.length === 0) return <span className="text-[var(--ink-faint)]">—</span>;
  return (
    <span className="mono text-xs">
      {entries.map(([status, n], i) => (
        <span key={status}>
          {i > 0 && <span className="text-[var(--ink-faint)]"> · </span>}
          <span className="text-[var(--ink-dim)]">{status}</span>{" "}
          <span className="text-white">{n}</span>
        </span>
      ))}
    </span>
  );
}

export default function RunsPage() {
  const [runs, setRuns] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api("/api/runs?limit=30")
      .then((body) => {
        setRuns(body.runs);
        setError(null);
      })
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, [load]);

  return (
    <main className="max-w-5xl mx-auto px-6 py-10">
      <header className="flex items-baseline justify-between border-b border-[var(--line)] pb-5 mb-0">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Hyperion</h1>
          <p className="micro-label mt-2">agent action ledger · rollback · audit</p>
        </div>
        <button
          onClick={load}
          className="mono text-xs text-[var(--ink-dim)] border border-[var(--line)] px-3 py-1.5 hover:text-white hover:border-white/30 transition-colors"
        >
          refresh
        </button>
      </header>

      {error && (
        <div className="panel mt-6 p-4 mono text-xs text-[var(--bad)]">
          API unreachable: {error}
          <div className="text-[var(--ink-dim)] mt-1">
            Start it with: <span className="text-white">poe dashboard</span> (port 8000)
          </div>
        </div>
      )}

      {runs === null && !error && (
        <div className="mono text-xs text-[var(--ink-faint)] mt-6">loading runs…</div>
      )}

      {runs && runs.length === 0 && (
        <div className="panel mt-6 p-8 text-center">
          <p className="text-sm text-[var(--ink-dim)]">No runs yet.</p>
          <p className="mono text-xs text-[var(--ink-faint)] mt-2">
            Run the bench, drive the gateway, or seed a demo: poe dashboard-seed
          </p>
        </div>
      )}

      {runs && runs.length > 0 && (
        <table className="w-full mt-0 text-left border-collapse">
          <thead>
            <tr className="border-b border-[var(--line)]">
              <th className="micro-label font-normal py-3 pr-4">run</th>
              <th className="micro-label font-normal py-3 pr-4">client</th>
              <th className="micro-label font-normal py-3 pr-4">started</th>
              <th className="micro-label font-normal py-3 pr-4 text-right">calls</th>
              <th className="micro-label font-normal py-3">status</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.id} className="border-b border-[var(--line)] hover:bg-white/[0.02]">
                <td className="py-3 pr-4">
                  <Link
                    href={`/runs/${run.id}`}
                    className="mono text-sm text-white underline decoration-white/20 underline-offset-4 hover:decoration-white"
                  >
                    {shortId(run.id)}
                  </Link>
                </td>
                <td className="py-3 pr-4 mono text-xs text-[var(--ink-dim)]">{run.client || "—"}</td>
                <td className="py-3 pr-4 mono text-xs text-[var(--ink-dim)]">
                  {run.started_at ? new Date(run.started_at).toLocaleString() : "—"}
                </td>
                <td className="py-3 pr-4 mono text-xs text-right text-white">{run.calls}</td>
                <td className="py-3">
                  <StatusCounts byStatus={run.by_status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
