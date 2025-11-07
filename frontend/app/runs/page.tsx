export default function RunsPage() {
  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div>
        <h1 style={{ fontSize: '28px', marginBottom: '8px', fontWeight: 600 }}>Runs</h1>
        <p style={{ color: '#94a3b8', maxWidth: '560px' }}>
          Track evaluation runs and production executions. This view will show latency, cost, trace verification status,
          and links into the ART ledger.
        </p>
      </div>
      <div
        style={{
          border: '1px dashed rgba(148, 163, 184, 0.4)',
          borderRadius: '12px',
          padding: '32px',
          textAlign: 'center',
          color: '#94a3b8'
        }}
      >
        Run history will appear here once provider integrations are wired up.
      </div>
    </section>
  );
}
