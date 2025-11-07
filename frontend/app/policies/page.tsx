export default function PoliciesPage() {
  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div>
        <h1 style={{ fontSize: '28px', marginBottom: '8px', fontWeight: 600 }}>Policies</h1>
        <p style={{ color: '#94a3b8', maxWidth: '560px' }}>
          Define guardrails for simulations, approvals, and production rollouts. Policy bundles will gate deploys based on
          evaluation outcomes, manual approvals, and environment readiness.
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
        Policy authoring UI coming soon.
      </div>
    </section>
  );
}
