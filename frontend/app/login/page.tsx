'use client';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:8000';

export default function LoginPage() {
  const handleSignIn = () => {
    window.location.href = `${BACKEND_URL}/auth/login`;
  };

  return (
    <section
      style={{
        margin: '0 auto',
        maxWidth: '420px',
        textAlign: 'center',
        paddingTop: '96px',
        display: 'flex',
        flexDirection: 'column',
        gap: '24px'
      }}
    >
      <h1 style={{ fontSize: '32px', fontWeight: 600 }}>Sign in</h1>
      <p style={{ color: '#94a3b8' }}>
        Use your enterprise identity provider to access the Hyperion control plane.
      </p>
      <button
        onClick={handleSignIn}
        style={{
          padding: '14px 20px',
          borderRadius: '999px',
          border: 'none',
          background: '#38bdf8',
          color: '#0f172a',
          fontWeight: 600,
          cursor: 'pointer'
        }}
      >
        Continue with SSO
      </button>
    </section>
  );
}
