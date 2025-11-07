export default function ConnectorsPage() {
  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div>
        <h1 style={{ fontSize: '28px', marginBottom: '8px', fontWeight: 600 }}>Connectors</h1>
        <p style={{ color: '#94a3b8', maxWidth: '560px' }}>
          Manage integrations with Salesforce, Slack, ServiceNow, and internal APIs. Connector entries control sandbox
          credentials for simulations and production credentials for canary rollouts.
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
        Connector registry placeholder.
      </div>
    </section>
  );
}
