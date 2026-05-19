'use client';

import { Button } from '@/components/ui/button';
import { signOut, useSession } from 'next-auth/react';

export function Topbar() {
  const { data: session, status } = useSession();
  const email = session?.user?.email ?? null;
  return (
    <header className="flex h-14 items-center justify-between border-b border-border bg-background px-6">
      <div className="text-sm font-medium text-muted-foreground">
        Multi-tenant, RBAC-aware, evaluation-driven enterprise RAG
      </div>
      <div className="flex items-center gap-3 text-sm">
        {status === 'authenticated' && email ? (
          <>
            <span className="text-muted-foreground">{email}</span>
            <Button variant="outline" size="sm" onClick={() => signOut()}>
              Sign out
            </Button>
          </>
        ) : status === 'loading' ? (
          <span className="text-muted-foreground">…</span>
        ) : (
          <span className="text-muted-foreground">Anonymous (dev token)</span>
        )}
      </div>
    </header>
  );
}
