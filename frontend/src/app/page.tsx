"use client";
import { useEffect, useState } from "react";

export default function Home() {
  const [traces, setTraces] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchTraces = async () => {
    try {
      const res = await fetch("http://localhost:8000/api/traces");
      const data = await res.json();
      setTraces(data.traces || []);
    } catch (e) {
      console.error("Failed to fetch traces", e);
    }
  };

  useEffect(() => {
    fetchTraces();
    const interval = setInterval(fetchTraces, 1500);
    return () => clearInterval(interval);
  }, []);

  const simulateSafeAction = async () => {
    setLoading(true);
    try {
      await fetch("http://localhost:8000/api/agent/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: "READ_CRM", query: "customer_data" }),
      });
    } catch (e) { }
    setLoading(false);
    fetchTraces();
  };

  const simulateDangerousAction = async () => {
    setLoading(true);
    try {
      await fetch("http://localhost:8000/api/agent/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: "DANGEROUS_ACTION", query: "delete_inbox" }),
      });
    } catch (e) { }
    setLoading(false);
    fetchTraces();
  };

  const simulateShadowAction = async () => {
    setLoading(true);
    try {
      await fetch("http://localhost:8000/api/agent/action?simulate=true", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: "WRITE_DOC", content: "Dry run email draft" }),
      });
    } catch (e) { }
    setLoading(false);
    fetchTraces();
  };

  return (
    <main className="min-h-screen bg-slate-950 text-slate-200 p-8 font-mono">
      <div className="max-w-6xl mx-auto space-y-8">
        <header className="border-b border-slate-800 pb-6 flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold bg-gradient-to-r from-emerald-400 to-cyan-500 bg-clip-text text-transparent">
              Zero-Trust Agent Governance
            </h1>
            <p className="text-slate-400 mt-2">State-as-a-Service & Rollback Intercept Control Plane</p>
          </div>
          <div className="flex gap-4">
            <button
              onClick={simulateShadowAction}
              disabled={loading}
              className="px-4 py-2 bg-blue-900/40 hover:bg-blue-900/60 text-blue-400 border border-blue-800/50 rounded-md transition-colors shadow-[0_0_15px_rgba(59,130,246,0.2)]"
            >
              Sys: Shadow Run
            </button>
            <button
              onClick={simulateSafeAction}
              disabled={loading}
              className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-emerald-400 rounded-md transition-colors border border-slate-700"
            >
              Sys: Safe Agent Call
            </button>
            <button
              onClick={simulateDangerousAction}
              disabled={loading}
              className="px-4 py-2 bg-red-900/40 hover:bg-red-900/60 text-red-400 border border-red-800/50 rounded-md transition-colors shadow-[0_0_15px_rgba(220,38,38,0.2)]"
            >
              Sys: Irreversible Agent Action
            </button>
          </div>
        </header>

        <section className="space-y-4">
          <h2 className="text-xl font-semibold text-slate-300">Time-Travel Debugging & Trace Logs</h2>
          <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-2xl">
            {traces.length === 0 ? (
              <div className="p-12 text-center text-slate-500">
                Awaiting Agent Execution Telemetry...
              </div>
            ) : (
              <div className="divide-y divide-slate-800/60 max-h-[600px] overflow-y-auto">
                {traces.map((trace: any) => (
                  <div key={trace.trace_id} className={`p-4 hover:bg-slate-800/30 transition duration-200 flex flex-col gap-2 ${trace.is_shadow_mode ? 'border-l-4 border-l-blue-500' : ''}`}>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <span
                          className={`px-2 py-0.5 rounded text-xs font-bold ${trace.status === "success" && !trace.is_shadow_mode
                            ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                            : trace.status === "success" && trace.is_shadow_mode
                              ? "bg-blue-500/20 text-blue-400 border border-blue-500/30"
                              : "bg-red-500/20 text-red-500 border border-red-500/30 animate-pulse"
                            }`}
                        >
                          {trace.status === "success" && !trace.is_shadow_mode ? "EXECUTED" : trace.status === "success" && trace.is_shadow_mode ? "SHADOW RUN" : "KILL SWITCH EVALUATION"}
                        </span>
                        <span className="text-sm font-semibold tracking-wider text-slate-300">{trace.method} {trace.path}</span>
                      </div>
                      <span className="text-xs text-slate-500">
                        {new Date(trace.timestamp * 1000).toLocaleTimeString()} · {trace.process_time_ms}ms latency
                      </span>
                    </div>

                    <div className="grid grid-cols-2 gap-4 mt-2">
                      <div className="bg-slate-950 p-3 rounded-md border border-slate-800/80">
                        <p className="text-[10px] text-slate-500 uppercase font-bold tracking-widest mb-1.5 border-b border-slate-800 pb-1">State Snapshot (Pre-Execution)</p>
                        <pre className="text-xs text-cyan-200/80 overflow-x-auto whitespace-pre-wrap">
                          {trace.request_body ? JSON.stringify(JSON.parse(trace.request_body), null, 2) : "No context diff mapped."}
                        </pre>
                      </div>

                      <div className={`p-3 rounded-md border ${trace.status === "failed" ? "bg-red-950/20 border-red-900/40" : "bg-slate-950 border-slate-800/80"}`}>
                        <p className="text-[10px] uppercase font-bold tracking-widest mb-1.5 border-b pb-1 flex justify-between items-center text-slate-500 border-slate-800">
                          <span>Compensating Transaction Readiness</span>
                          {trace.status === "failed" && <span className="text-red-400">🚨 ACTION HALTED</span>}
                        </p>
                        <div className="flex justify-between items-end">
                          <pre className="text-xs text-slate-400 overflow-x-auto max-w-[70%]">
                            {trace.status === "failed"
                              ? (trace.rollback_status === "completed"
                                ? "✅ Rollback Sequence Executed: State successfully restored via Compensating Transaction engine."
                                : trace.rollback_status === "in_progress"
                                  ? "⏳ Processing Compensating Transaction... Mapping API diff and reversing CRM state."
                                  : "CRITICAL: Agent bounded execution contract violated. Reversibility check initiated. Rollback engine holding state snapshot to prevent CRM corruption.")
                              : "State securely captured. No compensator fired."}
                          </pre>
                          {trace.status === "failed" && (
                            <a
                              href={`http://localhost:8000/api/compliance/export/${trace.trace_id}`}
                              target="_blank"
                              rel="noreferrer"
                              className="ml-4 px-3 py-1 bg-slate-800 hover:bg-slate-700 text-[10px] text-slate-300 rounded border border-slate-600 transition-colors whitespace-nowrap"
                            >
                              Download SOC2 Log
                            </a>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}
