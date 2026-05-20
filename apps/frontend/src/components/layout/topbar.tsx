'use client';

import { useQuery } from '@tanstack/react-query';
import { Bell, ChevronRight, LogOut, Search } from 'lucide-react';
import { signOut, useSession } from 'next-auth/react';
import { usePathname } from 'next/navigation';

import { Badge } from '@/components/ui/badge';
import { Kbd } from '@/components/ui/mono';
import { SignalChip } from '@/components/ui/signal-chip';
import type { Tone } from '@/lib/tone';
import { useApiClient } from '@/lib/use-api-client';

const ROUTE_LABELS: Record<string, string> = {
  '/dashboard': 'Dashboard',
  '/query-playground': 'Query Playground',
  '/collections': 'Collections',
  '/documents': 'Documents',
  '/evaluations': 'Evaluations',
  '/prompts': 'Prompts',
  '/audit': 'Audit',
  '/usage': 'Usage',
  '/settings': 'Settings',
};

function initials(value: string | null | undefined): string {
  if (!value) return 'SR';
  const local = value.split('@')[0];
  const parts = local.split(/[^a-zA-Z]+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return local.slice(0, 2).toUpperCase();
}

function latencyTone(p95: number | null): Tone {
  if (p95 === null) return 'neutral';
  if (p95 >= 600) return 'danger';
  if (p95 >= 300) return 'warning';
  return 'success';
}

function errorTone(rate: number | null): Tone {
  if (rate === null) return 'neutral';
  if (rate >= 0.05) return 'danger';
  if (rate >= 0.02) return 'warning';
  return 'success';
}

function costTone(utilizationPct: number | null): Tone {
  if (utilizationPct === null) return 'neutral';
  if (utilizationPct >= 100) return 'danger';
  if (utilizationPct >= 80) return 'warning';
  return 'success';
}

export function Topbar() {
  const { data: session, status } = useSession();
  const pathname = usePathname();
  const { client } = useApiClient();

  const tenant = useQuery({
    queryKey: ['me', 'tenant'],
    queryFn: () => client.myTenant(),
    retry: false,
  });

  // Last-hour ops signal (ADR-0038). Degrades to "—" while loading / on error.
  const metrics = useQuery({
    queryKey: ['metrics', '1h'],
    queryFn: () => client.getMetricsSummary({ window: '1h' }),
    retry: false,
    refetchInterval: 30_000,
  });
  const p95 = metrics.data?.latency.p95_ms ?? null;
  const errRate = metrics.data ? metrics.data.error_rate : null;

  // Month-to-date / budget-period spend (ADR-0039).
  const usage = useQuery({
    queryKey: ['usage', 'summary'],
    queryFn: () => client.getUsageSummary(),
    retry: false,
    refetchInterval: 60_000,
  });
  const cost = usage.data?.total_cost_usd ?? null;
  const costUtil = usage.data?.budget_utilization_pct ?? null;

  const email = session?.user?.email ?? null;
  const root = `/${pathname?.split('/').filter(Boolean)[0] ?? ''}`;
  const pageLabel = ROUTE_LABELS[root];
  const orgCrumb = tenant.data?.name ?? 'SentinelRAG';

  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-border bg-background px-5">
      {/* breadcrumb */}
      <div className="flex min-w-0 items-center gap-2 text-[13px]">
        <span className="truncate text-muted-foreground">{orgCrumb}</span>
        {pageLabel && (
          <>
            <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />
            <span className="truncate font-medium text-foreground">{pageLabel}</span>
          </>
        )}
      </div>

      {/* command-bar affordance */}
      <button
        type="button"
        className="mx-auto hidden h-8 w-full max-w-[520px] items-center gap-2 rounded-md border border-border bg-muted px-3 text-[13px] text-muted-foreground transition-colors hover:border-foreground/20 lg:flex"
      >
        <Search className="h-3.5 w-3.5" />
        <span className="flex-1 text-left">Search documents, collections, traces, prompts…</span>
        <Kbd>⌘K</Kbd>
      </button>

      {/* live ops signal */}
      <div className="ml-auto flex items-center gap-1.5">
        <Badge variant="success" dot pulse className="font-mono">
          sse · live
        </Badge>
        <div className="mx-1 hidden h-5 w-px bg-border xl:block" />
        <div className="hidden items-center gap-1.5 xl:flex">
          {/* p95 + error rate (last 1h, ADR-0038); cost MTD (ADR-0039). */}
          <SignalChip
            label="p95"
            value={p95 !== null ? `${Math.round(p95)}ms` : '—'}
            tone={latencyTone(p95)}
          />
          <SignalChip
            label="err 1h"
            value={errRate !== null ? `${(errRate * 100).toFixed(1)}%` : '—'}
            tone={errorTone(errRate)}
          />
          <SignalChip
            label="cost mtd"
            value={cost !== null ? `$${cost.toFixed(2)}` : '—'}
            tone={costTone(costUtil)}
          />
        </div>
        <div className="mx-1 hidden h-5 w-px bg-border sm:block" />
        <button
          type="button"
          className="grid h-8 w-8 place-items-center rounded-md border border-border bg-background text-foreground transition-colors hover:bg-muted"
          aria-label="Notifications"
        >
          <Bell className="h-[15px] w-[15px]" />
        </button>
        <div
          className="grid h-8 w-8 place-items-center rounded-full bg-primary text-[11px] font-semibold text-primary-foreground"
          title={email ?? 'Anonymous (dev token)'}
        >
          {initials(email)}
        </div>
        {status === 'authenticated' && email && (
          <button
            type="button"
            onClick={() => signOut()}
            className="grid h-8 w-8 place-items-center rounded-md border border-border bg-background text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            aria-label="Sign out"
            title="Sign out"
          >
            <LogOut className="h-[15px] w-[15px]" />
          </button>
        )}
      </div>
    </header>
  );
}
