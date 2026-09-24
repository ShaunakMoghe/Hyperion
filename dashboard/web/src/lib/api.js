"use client";

import { useEffect, useState } from "react";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export async function api(path, options) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text.slice(0, 200)}`);
  }
  return res.json();
}

export function shortId(id) {
  return id ? id.slice(0, 8) : "";
}

export function useRunEvents(runId, initial) {
  const [snapshot, setSnapshot] = useState(initial);
  const [live, setLive] = useState(false);
  useEffect(() => {
    if (!runId) return;
    const source = new EventSource(`${API_BASE}/api/runs/${runId}/events`);
    source.onopen = () => setLive(true);
    source.onerror = () => setLive(false);
    source.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (!data.gone && !data.stream_error && data.calls) setSnapshot(data);
      } catch {
        /* ignore malformed frames */
      }
    };
    return () => source.close();
  }, [runId]);
  return [snapshot, live];
}
