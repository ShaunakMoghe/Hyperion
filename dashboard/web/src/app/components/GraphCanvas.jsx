"use client";

import dynamic from "next/dynamic";
import { useCallback, useMemo } from "react";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), {
  ssr: false,
  loading: () => (
    <div className="p-12 text-center mono text-xs text-[var(--ink-faint)]">
      initializing graph…
    </div>
  ),
});

const COLORS = {
  executed: "#10b981",
  held: "#f59e0b",
  blocked: "#ef4444",
  failed: "#ef4444",
  rolled_back: "#525252",
};

function nodeColor(call) {
  if (call.rolledBack) return COLORS.rolled_back;
  return COLORS[call.status] || "#e5e5e5";
}

export default function GraphCanvas({ calls, edges, selectedId, onSelect }) {
  const graphData = useMemo(() => {
    const nodes = calls.map((call) => ({
      id: call.call_id,
      name: `${call.system}.${call.operation}`,
      seq: call.seq,
      status: call.status,
      rolledBack: call.rolledBack,
      color: nodeColor(call),
    }));
    const bySeq = [...calls].sort((a, b) => a.seq - b.seq);
    const links = [];
    const seen = new Set();
    for (const edge of edges || []) {
      const key = `${edge.depends_on_call_id}->${edge.call_id}`;
      if (!seen.has(key)) {
        seen.add(key);
        links.push({
          source: edge.depends_on_call_id,
          target: edge.call_id,
          dashed: edge.kind !== "provenance",
        });
      }
    }
    // Chain consecutive calls so isolated nodes still read in order.
    for (let i = 1; i < bySeq.length; i++) {
      const key = `${bySeq[i - 1].call_id}->${bySeq[i].call_id}`;
      if (!seen.has(key)) {
        seen.add(key);
        links.push({
          source: bySeq[i - 1].call_id,
          target: bySeq[i].call_id,
          dashed: true,
        });
      }
    }
    return { nodes, links };
  }, [calls, edges]);

  const paintNode = useCallback(
    (node, ctx, globalScale) => {
      const r = node.id === selectedId ? 9 : 7;
      ctx.beginPath();
      ctx.arc(node.x, node.y, r + 2, 0, 2 * Math.PI, false);
      ctx.fillStyle = node.id === selectedId ? "#ffffff" : node.color;
      ctx.fill();
      ctx.beginPath();
      ctx.arc(node.x, node.y, r, 0, 2 * Math.PI, false);
      ctx.fillStyle = "#000000";
      ctx.fill();
      ctx.beginPath();
      ctx.arc(node.x, node.y, r / 2.5, 0, 2 * Math.PI, false);
      ctx.fillStyle = node.id === selectedId ? "#ffffff" : node.color;
      ctx.fill();
      if (globalScale > 1.8) {
        const fontSize = 13 / globalScale;
        ctx.font = `${fontSize}px ui-monospace, Menlo, monospace`;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillStyle = "#e5e5e5";
        ctx.fillText(`#${node.seq} ${node.name}`, node.x, node.y + r + 7);
      }
    },
    [selectedId]
  );

  return (
    <div className="relative w-full bg-black overflow-hidden" style={{ height: 520 }}>
      <ForceGraph2D
        graphData={graphData}
        nodeLabel="name"
        nodeColor="color"
        linkColor={() => "#2a2a2a"}
        linkWidth={1.2}
        linkLineDash={(link) => (link.dashed ? [3, 4] : null)}
        linkDirectionalParticles={1}
        linkDirectionalParticleWidth={1.6}
        linkDirectionalParticleSpeed={0.004}
        linkDirectionalParticleColor={() => "#525252"}
        backgroundColor="#000000"
        onNodeClick={(node) => onSelect(node.id === selectedId ? null : node.id)}
        onBackgroundClick={() => onSelect(null)}
        nodeCanvasObject={paintNode}
        cooldownTicks={80}
        dagMode="lr"
        dagLevelDistance={70}
        minZoom={0.5}
        maxZoom={4}
      />
      <div className="absolute bottom-3 left-4 flex gap-4 mono text-[10px] text-[var(--ink-faint)]">
        <span><span style={{ color: COLORS.executed }}>●</span> executed</span>
        <span><span style={{ color: COLORS.held }}>●</span> held</span>
        <span><span style={{ color: COLORS.blocked }}>●</span> blocked / failed</span>
        <span><span style={{ color: COLORS.rolled_back }}>●</span> rolled back</span>
      </div>
    </div>
  );
}
