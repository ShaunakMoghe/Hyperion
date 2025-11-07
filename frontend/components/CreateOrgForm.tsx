'use client';

import { useState, useTransition } from 'react';
import { createOrganization } from '../lib/api';

export function CreateOrgForm({ onCreated }: { onCreated: () => Promise<void> | void }) {
  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);

    startTransition(async () => {
      try {
        await createOrganization({ name, slug: slug || undefined });
        setName('');
        setSlug('');
        await onCreated();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to create org');
      }
    });
  };

  return (
    <form
      onSubmit={handleSubmit}
      style={{
        display: 'flex',
        gap: '12px',
        alignItems: 'flex-end',
        marginBottom: '24px'
      }}
    >
      <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', flex: 1 }}>
        <span style={{ fontSize: '12px', letterSpacing: '0.08em', color: '#94a3b8' }}>Name</span>
        <input
          required
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder='Acme Corp'
          style={{
            padding: '12px 14px',
            borderRadius: '8px',
            border: '1px solid rgba(148, 163, 184, 0.3)',
            background: '#0f172a',
            color: '#e2e8f0'
          }}
        />
      </label>
      <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', width: '220px' }}>
        <span style={{ fontSize: '12px', letterSpacing: '0.08em', color: '#94a3b8' }}>Slug</span>
        <input
          value={slug}
          onChange={(event) => setSlug(event.target.value)}
          placeholder='acme'
          style={{
            padding: '12px 14px',
            borderRadius: '8px',
            border: '1px solid rgba(148, 163, 184, 0.3)',
            background: '#0f172a',
            color: '#e2e8f0'
          }}
        />
      </label>
      <button
        type='submit'
        disabled={isPending}
        style={{
          padding: '12px 20px',
          borderRadius: '999px',
          border: 'none',
          background: '#38bdf8',
          color: '#0f172a',
          fontWeight: 600,
          cursor: 'pointer'
        }}
      >
        {isPending ? 'Creating...' : 'Create Org'}
      </button>
      {error ? (
        <span style={{ color: '#f87171', fontSize: '14px' }}>{error}</span>
      ) : null}
    </form>
  );
}
