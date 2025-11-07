'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const links = [
  { href: '/projects', label: 'Projects' },
  { href: '/runs', label: 'Runs' },
  { href: '/policies', label: 'Policies' },
  { href: '/connectors', label: 'Connectors' },
  { href: '/secrets', label: 'Secrets' },
  { href: '/status', label: 'Status' }
];

export function NavBar() {
  const pathname = usePathname();

  return (
    <header
      style={{
        backgroundColor: '#0b1120',
        borderBottom: '1px solid rgba(148, 163, 184, 0.24)',
        padding: '0 24px'
      }}
    >
      <div
        style={{
          maxWidth: '1200px',
          margin: '0 auto',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          height: '64px'
        }}
      >
        <div style={{ fontWeight: 600, fontSize: '18px', letterSpacing: '0.02em' }}>Hyperion Control</div>
        <nav style={{ display: 'flex', gap: '16px' }}>
          {links.map((link) => {
            const isActive = pathname?.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                style={{
                  color: isActive ? '#38bdf8' : '#94a3b8',
                  fontWeight: isActive ? 600 : 500,
                  fontSize: '14px',
                  textTransform: 'uppercase',
                  letterSpacing: '0.08em'
                }}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', color: '#cbd5f5', fontSize: '13px' }}>
          <span>Acme Org</span>
          <div
            style={{
              width: '32px',
              height: '32px',
              borderRadius: '50%',
              backgroundColor: '#1e293b',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 600
            }}
          >
            PL
          </div>
        </div>
      </div>
    </header>
  );
}
