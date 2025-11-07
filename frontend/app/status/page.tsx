import { fetchJson, listAuditLogs } from "../../lib/api";

type HealthResponse = {
  status: string;
  app: string;
  environment: string;
};

type AuditEntry = {
  id: string;
  action: string;
  target?: string;
  created_at: string;
};

export default async function StatusPage() {
  let health: HealthResponse | null = null;
  let audit: AuditEntry[] = [];

  try {
    health = await fetchJson<HealthResponse>("/healthz");
    audit = await listAuditLogs();
  } catch (error) {
    console.error("Failed to load status", error);
  }

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      <div>
        <h1 style={{ fontSize: "28px", marginBottom: "8px", fontWeight: 600 }}>System Status</h1>
        <p style={{ color: "#94a3b8", maxWidth: "560px" }}>
          Runtime health of the Hyperion control plane, including recent audit events.
        </p>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: "16px"
        }}
      >
        <div
          style={{
            borderRadius: "12px",
            padding: "20px",
            background: "rgba(56, 189, 248, 0.08)",
            border: "1px solid rgba(56, 189, 248, 0.24)"
          }}
        >
          <div style={{ fontSize: "12px", letterSpacing: "0.08em", textTransform: "uppercase", color: "#38bdf8" }}>
            Backend
          </div>
          <div style={{ fontSize: "24px", fontWeight: 600 }}>
            {health?.status === "ok" ? "Operational" : "Unknown"}
          </div>
          <div style={{ color: "#94a3b8", fontSize: "13px", marginTop: "4px" }}>
            {health ? `${health.app} (${health.environment})` : "Failed to reach backend"}
          </div>
        </div>
      </div>

      <div style={{ marginTop: "24px" }}>
        <h2 style={{ fontSize: "18px", marginBottom: "12px", fontWeight: 600 }}>Recent audit events</h2>
        {audit.length === 0 ? (
          <div style={{ color: "#94a3b8" }}>No audit entries yet.</div>
        ) : (
          <ul
            style={{
              listStyle: "none",
              padding: 0,
              margin: 0,
              display: "flex",
              flexDirection: "column",
              gap: "12px"
            }}
          >
            {audit.slice(0, 5).map((entry) => (
              <li
                key={entry.id}
                style={{
                  borderRadius: "10px",
                  border: "1px solid rgba(148, 163, 184, 0.2)",
                  padding: "16px",
                  display: "flex",
                  flexDirection: "column",
                  gap: "6px"
                }}
              >
                <div style={{ fontWeight: 600 }}>{entry.action}</div>
                <div style={{ color: "#94a3b8", fontSize: "13px" }}>{entry.target ?? "—"}</div>
                <div style={{ color: "#64748b", fontSize: "12px" }}>{new Date(entry.created_at).toLocaleString()}</div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
