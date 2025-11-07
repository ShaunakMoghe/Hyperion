import './globals.css';
import { NavBar } from '../components/NavBar';
import type { Metadata } from 'next';
import type { ReactNode } from 'react';

export const metadata: Metadata = {
  title: 'Hyperion Console',
  description: 'Control plane for AI releases'
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang='en'>
      <body>
        <NavBar />
        <main
          style={{
            maxWidth: '1200px',
            margin: '0 auto',
            padding: '32px 24px'
          }}
        >
          {children}
        </main>
      </body>
    </html>
  );
}
