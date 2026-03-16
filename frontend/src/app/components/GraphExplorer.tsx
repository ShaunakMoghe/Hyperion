import React, { useMemo, useState, useCallback, useRef, useEffect } from 'react';
import dynamic from 'next/dynamic';
import { Database, ShieldAlert, X } from 'lucide-react';

// ForceGraph2D requires window, so we must load it dynamically
const ForceGraph2D = dynamic(() => import('react-force-graph-2d'), { 
  ssr: false,
  loading: () => <div className="p-12 text-center text-slate-500 text-sm">Initializing Causal Topology Mesh...</div>
});

export default function GraphExplorer({ traces }: { traces: any[] }) {
  const [selectedNode, setSelectedNode] = useState<any | null>(null);

  // Prevent layout thrashing from the 1.5s telemetry poll
  const [stableTraces, setStableTraces] = useState<any[]>(traces);
  
  useEffect(() => {
    const currentKeys = stableTraces.map(t => t.trace_id + t.status).join(',');
    const newKeys = traces.map(t => t.trace_id + t.status).join(',');
    if (currentKeys !== newKeys) {
      setStableTraces(traces);
    }
  }, [traces, stableTraces]);

  // Map chronological traces into a physics directed graph
  const graphData = useMemo(() => {
    // Start with a central "Hub" node
    const nodes: any[] = [
      { id: 'core', name: 'Hyperion Oracle', isCore: true }
    ];
    const links: any[] = [];

    stableTraces.forEach((trace, idx) => {
      const isShadow = trace.is_shadow_mode;
      const isSuccess = trace.status === "success";
      
      let color = '#ef4444'; // Crimson (Halted)
      if (isSuccess && !isShadow) color = '#10b981'; // Emerald (Executed)
      else if (isSuccess && isShadow) color = '#3b82f6'; // Blue (Shadow)

      nodes.push({
        id: trace.trace_id,
        name: `[${trace.method}] ${trace.path}`,
        color,
        traceData: trace
      });

      // Link logic: Form a chain of execution, where the first node connects to the Core.
      if (idx === 0) {
        links.push({ source: 'core', target: trace.trace_id, color: '#1F1F1F' });
      } else {
        links.push({ source: stableTraces[idx - 1].trace_id, target: trace.trace_id, color: '#1F1F1F' });
      }
    });

    return { nodes, links };
  }, [stableTraces]);

  // Custom Canvas Rendering for Amoled UI Nodes
  const paintNode = useCallback((node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const { x, y, color, isCore } = node;
    const r = isCore ? 14 : 7;
    
    // Draw outer glow / ring
    ctx.beginPath();
    ctx.arc(x, y, r + 2, 0, 2 * Math.PI, false);
    ctx.fillStyle = isCore ? '#0891b2' : color; // Cyan for core, status color for traces
    ctx.fill();

    // Draw dark inner core
    ctx.beginPath();
    ctx.arc(x, y, r, 0, 2 * Math.PI, false);
    ctx.fillStyle = '#000000';
    ctx.fill();

    // Draw inner bright dot
    ctx.beginPath();
    ctx.arc(x, y, r / 2.5, 0, 2 * Math.PI, false);
    ctx.fillStyle = isCore ? '#22d3ee' : color;
    ctx.fill();
    
    // Text Label Rendering (only if deeply zoomed in to prevent overlapping cluster text)
    if (globalScale > 2.5) {
      const label = node.name;
      const fontSize = 14 / globalScale;
      ctx.font = `600 ${fontSize}px "Google Sans", sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillStyle = isCore ? '#22d3ee' : '#e5e5e5';
      ctx.fillText(label, x, y + r + 8);
    }
  }, []);

  return (
    <div className="relative w-full h-full bg-[#000000] overflow-hidden rounded-b-2xl">
      <ForceGraph2D
        graphData={graphData}
        nodeLabel="name"
        nodeColor="color"
        linkColor={() => '#1F1F1F'}
        linkWidth={1.5}
        // Peak Sci-Fi: Floating glowing directional particles traveling along the links
        linkDirectionalParticles={2}
        linkDirectionalParticleWidth={2}
        linkDirectionalParticleSpeed={0.005}
        linkDirectionalParticleColor={(link: any) => link.target.color || '#22d3ee'}
        backgroundColor="#000000"
        onNodeClick={(node) => setSelectedNode(node)}
        nodeCanvasObject={paintNode}
        cooldownTicks={100}
        // Organize into a standard Git-style chronological tree
        dagMode="lr"
        dagLevelDistance={60}
        // Disable zooming to just let it drift naturally unless scrolled
        minZoom={0.5}
        maxZoom={4}
      />

      {/* Floating Holographic Info Panel */}
      {selectedNode && !selectedNode.isCore && (
        <div className="absolute top-4 right-4 w-[380px] bg-[#0a0a0a]/95 backdrop-blur-xl border border-[#1F1F1F] rounded-2xl shadow-2xl p-5 z-10 flex flex-col gap-4">
          <div className="flex justify-between items-start">
            <div>
              <span className={`px-2 py-1 rounded text-[10px] font-bold tracking-wider uppercase border ${
                  selectedNode.traceData.status === "success" && !selectedNode.traceData.is_shadow_mode
                    ? "bg-emerald-950/20 text-emerald-400 border-emerald-900/40"
                    : selectedNode.traceData.status === "success" && selectedNode.traceData.is_shadow_mode
                      ? "bg-blue-950/20 text-blue-400 border-blue-900/40"
                      : "bg-red-950/20 text-red-500 border-red-900/40"
                }`}>
                {selectedNode.traceData.status === "success" && !selectedNode.traceData.is_shadow_mode ? "EXECUTED" : 
                 selectedNode.traceData.status === "success" && selectedNode.traceData.is_shadow_mode ? "SHADOW" : "HALTED"}
              </span>
            </div>
            <button onClick={() => setSelectedNode(null)} className="text-slate-500 hover:text-white transition-colors">
              <X className="w-4 h-4" />
            </button>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-slate-200 font-mono tracking-tight mb-1">
              {selectedNode.traceData.method} <span className="text-slate-400">{selectedNode.traceData.path}</span>
            </h3>
            <span className="text-xs font-medium text-slate-500 font-mono mb-3 block">
              {new Date(selectedNode.traceData.timestamp * 1000).toLocaleTimeString()}
            </span>
          </div>

          <div className="bg-[#000] p-3 rounded-xl border border-[#1F1F1F]">
            <p className="text-xs text-slate-500 uppercase font-bold tracking-wide mb-2 flex items-center gap-1.5">
              <Database className="w-3 h-3 text-cyan-500/50" /> State Diff Payload
            </p>
            <pre className="text-xs text-slate-300 overflow-x-auto whitespace-pre-wrap font-mono m-0 max-h-48">
              {selectedNode.traceData.request_body ? JSON.stringify(JSON.parse(selectedNode.traceData.request_body), null, 2) : "No context diff."}
            </pre>
          </div>

          {selectedNode.traceData.status === "failed" && (
            <div className="bg-[#1A0505] p-3 rounded-xl border border-red-900/30 flex flex-col gap-2">
              <p className="text-xs uppercase font-bold tracking-wide flex justify-between items-center text-red-500">
                <span className="flex items-center gap-1.5"><ShieldAlert className="w-4 h-4" /> Rollback Enacted</span>
              </p>
              <p className="text-xs text-slate-400 font-sans tracking-wide">
                {selectedNode.traceData.rollback_status === "completed"
                  ? "Action safely rolled back out of database."
                  : "Contract Violation. Evaluating rollback procedure."}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
