"use client";
import { useEffect, useState } from "react";
import {
  ShieldAlert,
  Activity,
  Database,
  Cpu,
  Settings2,
  Send,
  Eclipse,
  Lock,
  Zap,
  CheckCircle2,
  AlertTriangle
} from "lucide-react";
import GraphExplorer from "./components/GraphExplorer";

export default function Home() {
  const [traces, setTraces] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'traces' | 'graph'>('traces');

  useEffect(() => {
    const saved = localStorage.getItem('hyperion_active_tab');
    if (saved === 'traces' || saved === 'graph') {
      setActiveTab(saved);
    }
  }, []);

  useEffect(() => {
    localStorage.setItem('hyperion_active_tab', activeTab);
  }, [activeTab]);

  const fetchTraces = async () => {
    try {
      const res = await fetch("http://localhost:8000/api/traces");
      const data = await res.json();
      setTraces(data.traces || []);
    } catch (e) {
      console.error("Failed to fetch traces", e);
    }
  };

  const [chatPrompt, setChatPrompt] = useState("");
  const [chatResponse, setChatResponse] = useState("");
  const [chatLoading, setChatLoading] = useState(false);

  const handleChatSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!chatPrompt.trim()) return;

    setChatLoading(true);
    setChatResponse("");
    try {
      const res = await fetch("http://localhost:8000/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: chatPrompt }),
      });
      const data = await res.json();
      const replyContent = data.reply;
      if (typeof replyContent === 'string') {
        setChatResponse(replyContent || "Agent execution failed.");
      } else {
        setChatResponse(JSON.stringify(replyContent, null, 2));
      }
    } catch (err) {
      setChatResponse("Error: Could not reach agent backend.");
    }
    setChatLoading(false);
    fetchTraces();
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
    <div className="flex h-screen w-full bg-[#000000] text-[#e5e5e5] overflow-hidden">

      {/* Left Sidebar Navigation */}
      <aside className="w-64 border-r border-[#1F1F1F] bg-[#0a0a0a] hidden md:flex flex-col">
        <div className="h-16 flex items-center px-6 border-b border-[#1F1F1F]">
          <Eclipse className="w-5 h-5 mr-3 text-cyan-400" />
          <span className="text-lg font-semibold tracking-wide text-white">Hyperion</span>
        </div>

        <nav className="flex-1 py-4">
          <ul className="space-y-1 px-3">
            <li>
              <button 
                onClick={() => setActiveTab('traces')}
                className={`w-full flex items-center px-3 py-2 text-sm font-medium rounded-lg transition-colors border ${activeTab === 'traces' ? 'bg-[#111] text-white border-[#1F1F1F]' : 'border-transparent text-slate-400 hover:text-white hover:bg-[#111]'}`}
              >
                <Activity className={`w-4 h-4 mr-3 ${activeTab === 'traces' ? 'text-cyan-400' : ''}`} />
                Live Telemetry
              </button>
            </li>
            <li>
              <button className="w-full flex items-center px-3 py-2 text-sm font-medium rounded-lg hover:bg-[#111] text-slate-400 hover:text-white transition-colors border border-transparent">
                <ShieldAlert className="w-4 h-4 mr-3" />
                Kill Switches
              </button>
            </li>
            <li>
              <button 
                onClick={() => setActiveTab('graph')}
                className={`w-full flex items-center px-3 py-2 text-sm font-medium rounded-lg transition-colors border ${activeTab === 'graph' ? 'bg-[#111] text-white border-[#1F1F1F]' : 'border-transparent text-slate-400 hover:text-white hover:bg-[#111]'}`}
              >
                <Database className={`w-4 h-4 mr-3 ${activeTab === 'graph' ? 'text-cyan-400' : ''}`} />
                Graph Explorer
              </button>
            </li>
          </ul>
        </nav>

        <div className="p-4 border-t border-[#1F1F1F]">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-cyan-950/30 flex items-center justify-center border border-cyan-900/50">
              <Cpu className="w-4 h-4 text-cyan-400" />
            </div>
            <div>
              <p className="text-xs font-medium text-white">Proxy Gateway</p>
              <p className="text-[10px] text-emerald-400 flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 block pb-px"></span> Connected
              </p>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Center Workspace */}
      <main className="flex-1 flex flex-col min-w-0 bg-[#000000]">

        {/* Header Toolbar */}
        <header className="h-16 border-b border-[#1F1F1F] flex items-center justify-between px-6 shrink-0 bg-[#0a0a0a]/50">
          <div>
            <h1 className="text-base font-semibold text-slate-300">
              Agent Control Plane
            </h1>
          </div>
          <div className="flex gap-2">
            <div className="relative group">
              <button
                onClick={simulateShadowAction}
                disabled={loading}
                className="p-2 bg-[#0a0a0a] hover:bg-[#111111] text-blue-400 border border-[#1F1F1F] rounded-lg transition-colors flex items-center justify-center"
              >
                <Lock className="w-4 h-4" />
              </button>
              <span className="absolute -bottom-8 left-1/2 -translate-x-1/2 px-2 py-1 bg-[#1F1F1F] text-xs text-white rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none z-10 border border-[#2A2A2A]">
                Shadow Run
              </span>
            </div>

            <div className="relative group">
              <button
                onClick={simulateSafeAction}
                disabled={loading}
                className="p-2 bg-[#0a0a0a] hover:bg-[#111111] text-emerald-400 border border-[#1F1F1F] rounded-lg transition-colors flex items-center justify-center"
              >
                <CheckCircle2 className="w-4 h-4" />
              </button>
              <span className="absolute -bottom-8 left-1/2 -translate-x-1/2 px-2 py-1 bg-[#1F1F1F] text-xs text-white rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none z-10 border border-[#2A2A2A]">
                Safe Action
              </span>
            </div>

            <div className="relative group">
              <button
                onClick={simulateDangerousAction}
                disabled={loading}
                className="p-2 bg-[#0a0a0a] hover:bg-[#1A0505] text-red-500 border border-[#1F1F1F] hover:border-red-900/40 rounded-lg transition-colors flex items-center justify-center"
              >
                <AlertTriangle className="w-4 h-4" />
              </button>
              <span className="absolute -bottom-8 left-1/2 -translate-x-1/2 px-2 py-1 bg-[#1F1F1F] text-xs text-white rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none z-10 border border-[#2A2A2A]">
                Irreversible Action
              </span>
            </div>
          </div>
        </header>

        {/* Scrollable Center Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">

          {/* Agent Sandbox */}
          <section className="space-y-3">
            <h2 className="text-sm font-bold text-slate-500 uppercase tracking-widest pl-1">Agent Sandbox</h2>
            <div className="bg-[#0a0a0a] border border-[#1F1F1F] rounded-2xl p-4 flex flex-col gap-4">
              <form onSubmit={handleChatSubmit} className="relative flex items-center">
                <input
                  type="text"
                  value={chatPrompt}
                  onChange={(e) => setChatPrompt(e.target.value)}
                  placeholder="Instruct the agent (e.g., 'Read CRM data for user_123, then delete their inbox')"
                  className="w-full bg-[#111111] border border-[#1F1F1F] rounded-xl pl-4 pr-12 py-3 text-sm text-slate-200 focus:outline-none focus:border-cyan-900/50 transition-colors placeholder-slate-600 shadow-inner"
                  disabled={chatLoading}
                />
                <button
                  type="submit"
                  disabled={chatLoading}
                  className="absolute right-2 p-2 bg-[#1A1A1A] hover:bg-[#2A2A2A] text-cyan-400 rounded-lg transition-colors disabled:opacity-50 border border-[#222]"
                >
                  <Send className="w-4 h-4" />
                </button>
              </form>

              {chatResponse && (
                <div className="bg-[#000] p-4 rounded-xl border border-[#1F1F1F]">
                  <p className="text-xs text-slate-500 uppercase font-bold tracking-widest mb-2 flex items-center gap-2">
                    <Zap className="w-3 h-3 text-cyan-400" />
                    Agent Reasoning
                  </p>
                  <div className="text-sm text-slate-300 whitespace-pre-wrap leading-relaxed">{chatResponse}</div>
                </div>
              )}
            </div>
          </section>

          {/* Data Views */}
          <section className="space-y-3 flex-1 flex flex-col h-[500px]">
            <h2 className="text-sm font-bold text-slate-500 uppercase tracking-widest pl-1">
              {activeTab === 'traces' ? 'Time-Travel Traces' : 'Causal C-Graph Computation'}
            </h2>
            <div className="bg-[#0a0a0a] border border-[#1F1F1F] rounded-2xl overflow-hidden shadow-sm flex-1 flex flex-col">
              {traces.length === 0 ? (
                <div className="p-12 text-center text-slate-600 text-sm flex-1 flex items-center justify-center">
                  Awaiting Agent Execution Telemetry...
                </div>
              ) : activeTab === 'graph' ? (
                <div className="flex-1 w-full h-full min-h-[500px]">
                  <GraphExplorer traces={traces} />
                </div>
              ) : (
                <div className="divide-y divide-[#1F1F1F] overflow-y-auto flex-1">
                  {traces.map((trace: any) => (
                    <div key={trace.trace_id} className={`p-5 hover:bg-[#0f0f0f] transition-colors flex flex-col gap-3 ${trace.is_shadow_mode ? 'border-l-4 border-l-blue-900' : 'border-l-4 border-l-transparent'}`}>

                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          <span
                            className={`px-2 py-1 rounded text-xs font-bold tracking-wider uppercase border ${trace.status === "success" && !trace.is_shadow_mode
                                ? "bg-emerald-950/20 text-emerald-400 border-emerald-900/40"
                                : trace.status === "success" && trace.is_shadow_mode
                                  ? "bg-blue-950/20 text-blue-400 border-blue-900/40"
                                  : "bg-red-950/20 text-red-500 border-red-900/40"
                              }`}
                          >
                            {trace.status === "success" && !trace.is_shadow_mode ? "EXECUTED" : trace.status === "success" && trace.is_shadow_mode ? "SHADOW" : "HALTED"}
                          </span>
                          <span className="text-sm font-semibold text-slate-200 font-mono tracking-tight">
                            {trace.method} <span className="text-slate-400">{trace.path}</span>
                          </span>
                        </div>
                        <span className="text-xs font-medium text-slate-500 font-mono">
                          {new Date(trace.timestamp * 1000).toLocaleTimeString()}
                        </span>
                      </div>

                      <div className="flex flex-col gap-2">
                        <div className="bg-[#000] p-3 rounded-xl border border-[#1F1F1F]">
                          <p className="text-xs text-slate-500 uppercase font-bold tracking-wide mb-2 flex items-center gap-1.5">
                            <Database className="w-3 h-3 text-cyan-500/50" /> State Diff
                          </p>
                          <pre className="text-xs text-slate-300 overflow-x-auto whitespace-pre-wrap font-mono">
                            {trace.request_body ? JSON.stringify(JSON.parse(trace.request_body), null, 2) : "No context diff mapped."}
                          </pre>
                        </div>

                        {trace.status === "failed" && (
                          <div className="bg-[#1A0505] p-3 rounded-xl border border-red-900/30 flex flex-col gap-2">
                            <p className="text-xs uppercase font-bold tracking-wide flex justify-between items-center text-red-500">
                              <span className="flex items-center gap-1.5"><ShieldAlert className="w-4 h-4" /> Rollback Status</span>
                            </p>
                            <p className="text-xs text-slate-400 font-sans tracking-wide">
                              {trace.rollback_status === "completed"
                                ? "Action safely rolled back. Trace recorded in Governance Ledger."
                                : "Contract Violation. Evaluating rollback procedure."}
                            </p>
                            <div className="mt-1">
                              <a
                                href={`http://localhost:8000/api/compliance/export/${trace.trace_id}`}
                                target="_blank"
                                rel="noreferrer"
                                className="inline-block px-3 py-1.5 bg-[#111] hover:bg-[#1A1A1A] text-xs text-slate-300 rounded-lg border border-[#222] transition-colors font-semibold tracking-wide"
                              >
                                Download SOC2 Log
                              </a>
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>
        </div>
      </main>

      {/* Right Sidebar - Config Panel */}
      <aside className="w-72 border-l border-[#1F1F1F] bg-[#0a0a0a] hidden lg:flex flex-col shrink-0">
        <div className="h-16 flex items-center px-5 border-b border-[#1F1F1F]">
          <Settings2 className="w-4 h-4 mr-2 text-slate-400" />
          <span className="text-base font-semibold text-slate-200">Governance Settings</span>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-6">
          <div className="space-y-4">
            <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest pl-1">Model Context</h3>
            <div className="space-y-2 bg-[#111] p-3 rounded-xl border border-[#1F1F1F]">
              <label className="text-sm font-medium text-slate-400 block ml-1">Agent Framework</label>
              <select className="w-full bg-[#000] border border-[#2A2A2A] text-slate-200 text-sm font-medium rounded-lg py-2.5 px-3 focus:outline-none focus:border-cyan-900/50 appearance-none h-9">
                <option>LangGraph (Current)</option>
                <option>AutoGen Integration</option>
                <option>CrewAI Setup</option>
              </select>
            </div>

            <div className="pt-2 bg-[#111] p-3 rounded-xl border border-[#1F1F1F] flex justify-between items-center">
              <div>
                <label className="text-sm font-semibold text-slate-300">Strict Contract Mode</label>
                <p className="text-xs text-slate-500 mt-0.5">Halt undefined API calls.</p>
              </div>
              <div className="w-8 h-4 bg-emerald-950/40 rounded-full border border-emerald-900 flex items-center shrink-0 pl-[18px]">
                <div className="w-2.5 h-2.5 bg-emerald-500 rounded-full"></div>
              </div>
            </div>
          </div>

          <div className="space-y-4 pt-2">
            <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest pl-1">Telemetry Bounds</h3>

            <div className="bg-[#111] p-3 rounded-xl border border-[#1F1F1F] space-y-5">
              <div>
                <div className="flex justify-between text-sm font-medium mb-2">
                  <span className="text-slate-400">Max Causal Depth</span>
                  <span className="text-cyan-400 font-mono font-bold text-xs">20</span>
                </div>
                <div className="h-1 w-full bg-[#000] rounded-full overflow-hidden border border-[#1F1F1F]">
                  <div className="h-full bg-cyan-600/60 w-2/3"></div>
                </div>
              </div>

              <div>
                <div className="flex justify-between text-sm font-medium mb-2">
                  <span className="text-slate-400">Rollback Timeout</span>
                  <span className="text-cyan-400 font-mono font-bold text-xs">10s</span>
                </div>
                <div className="h-1 w-full bg-[#000] rounded-full overflow-hidden border border-[#1F1F1F]">
                  <div className="h-full bg-cyan-600/60 w-1/4"></div>
                </div>
              </div>
            </div>

          </div>
        </div>
      </aside>

    </div>
  );
}
