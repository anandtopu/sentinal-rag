import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import { Sidebar } from '@/components/layout/sidebar';
import { Topbar } from '@/components/layout/topbar';

import './globals.css';
import { Providers } from './providers';

export const metadata: Metadata = {
  title: 'SentinelRAG',
  description: 'Multi-tenant, RBAC-aware, evaluation-driven enterprise RAG platform.',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen bg-background text-foreground antialiased">
        <Providers>
          <div className="flex min-h-screen">
            <Sidebar />
            <div className="flex flex-1 flex-col">
              <Topbar />
              <main className="flex-1 overflow-y-auto bg-muted/50 px-6 py-6 lg:px-7">
                {children}
              </main>
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
