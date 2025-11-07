'use client';

import { useCallback, useEffect, useState } from 'react';
import { CreateOrgForm } from '../../components/CreateOrgForm';
import { listOrganizations } from '../../lib/api';

type Org = {
  id: string;
  name: string;
  slug: string;
};

export default function ProjectsPage() {
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await listOrganizations();
      setOrgs(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load organizations');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div>
        <h1 style={{ fontSize: '28px', marginBottom: '8px', fontWeight: 600 }}>Projects</h1>
        <p style={{ color: '#94a3b8', maxWidth: '560px' }}>
          Manage customer orgs that deploy Hyperion agents. Create a new organization to provision isolated provider
          credentials and policy sets.
        </p>
      </div>

      <CreateOrgForm onCreated={load} />

      {isLoading ? (
        <div style={{ color: '#94a3b8' }}>Loading organizations...</div>
      ) : error ? (
        <div style={{ color: '#f87171' }}>{error}</div>
      ) : orgs.length === 0 ? (
        <div
          style={{
            border: '1px dashed rgba(148, 163, 184, 0.4)',
            borderRadius: '12px',
            padding: '32px',
            textAlign: 'center',
            color: '#94a3b8'
          }}
        >
          No organizations yet. Create one to get started.
        </div>
      ) : (
        <table
          style={{
            width: '100%',
            borderCollapse: 'collapse',
            borderRadius: '12px',
            overflow: 'hidden'
          }}
        >
          <thead
            style={{
              background: 'rgba(148, 163, 184, 0.08)',
              color: '#cbd5f5',
              fontSize: '12px',
              textTransform: 'uppercase',
              letterSpacing: '0.1em'
            }}
          >
            <tr>
              <th style={{ textAlign: 'left', padding: '14px 16px' }}>Name</th>
              <th style={{ textAlign: 'left', padding: '14px 16px' }}>Slug</th>
              <th style={{ textAlign: 'left', padding: '14px 16px' }}>ID</th>
            </tr>
          </thead>
          <tbody>
            {orgs.map((org) => (
              <tr key={org.id} style={{ borderBottom: '1px solid rgba(148, 163, 184, 0.1)' }}>
                <td style={{ padding: '16px' }}>{org.name}</td>
                <td style={{ padding: '16px', color: '#38bdf8' }}>{org.slug}</td>
                <td style={{ padding: '16px', fontFamily: 'monospace', fontSize: '13px', color: '#94a3b8' }}>{org.id}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
