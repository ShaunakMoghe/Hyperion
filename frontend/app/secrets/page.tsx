export default function SecretsPage() {
  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div>
        <h1 style={{ fontSize: '28px', marginBottom: '8px', fontWeight: 600 }}>Secrets</h1>
        <p style={{ color: '#94a3b8', maxWidth: '560px' }}>
          Store provider API keys and connector credentials. Secrets remain masked by default and rotations are logged in
          the audit trail.
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
        Secrets vault integration coming soon.
      </div>
    </section>
  );
}
