'use client';

import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Activity,
  ArrowRight,
  Bookmark,
  Clock,
  Database,
  type LucideIcon,
  RefreshCw,
  Shield,
  Sparkles,
} from 'lucide-react';
import Link from 'next/link';
import type { ReactNode } from 'react';

import { PageHeader } from '@/components/layout/page-header';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { DataBar } from '@/components/ui/data-bar';
import { Mono } from '@/components/ui/mono';
import { SectionLabel } from '@/components/ui/section-label';
import { MiniSpark } from '@/components/ui/spark';
import type { IngestionJob, QuerySessionListItem } from '@/lib/api-types';
import { type Tone, scoreTone, statusTone, toneBadgeVariant, toneColor } from '@/lib/tone';
import { useApiClient } from '@/lib/use-api-client';
import { cn, formatNumber } from '@/lib/utils';

const PILLARS: { icon: LucideIcon; title: string; desc: string }[] = [
  {
    icon: Shield,
    title: 'RBAC at retrieval',
    desc: 'RBAC injected at retrieval time, never post-mask.',
  },
  { icon: Database, title: 'Tenant RLS', desc: 'Postgres row-level security as defense-in-depth.' },
  { icon: Activity, title: 'Traceable answers', desc: 'Every reply pinned to query_session_id.' },
  {
    icon: Bookmark,
    title: 'Versioned prompts',
    desc: 'Prompts are versioned artifacts; prompt_version_id persisted.',
  },
];

const RUNNING = new Set(['processing', 'running', 'queued', 'pending']);

export default function DashboardPage() {
  const { client } = useApiClient();
  const qc = useQueryClient();

  const collections = useQuery({
    queryKey: ['collections'],
    queryFn: () => client.listCollections({ limit: 200 }),
    retry: false,
  });
  const evalRuns = useQuery({ queryKey: ['eval-runs'], queryFn: () => client.listEvalRuns({}) });

  const firstCollectionId = collections.data?.items[0]?.id;
  const jobs = useQuery({
    queryKey: ['ingestion-jobs', firstCollectionId],
    queryFn: () => client.listIngestionJobs(firstCollectionId as string),
    enabled: Boolean(firstCollectionId),
    refetchInterval: 5_000,
  });

  const latestRunId =
    evalRuns.data?.find((r) => r.status === 'completed')?.id ?? evalRuns.data?.[0]?.id;
  const latestRun = useQuery({
    queryKey: ['eval-run', latestRunId],
    queryFn: () => client.getEvalRun(latestRunId as string),
    enabled: Boolean(latestRunId),
  });

  // 24h ops vitals (ADR-0038) + month-to-date cost (ADR-0039).
  const metrics = useQuery({
    queryKey: ['metrics', '24h'],
    queryFn: () => client.getMetricsSummary({ window: '24h' }),
    retry: false,
    refetchInterval: 30_000,
  });
  const usage = useQuery({
    queryKey: ['usage', 'summary'],
    queryFn: () => client.getUsageSummary(),
    retry: false,
    refetchInterval: 60_000,
  });
  // Recent query feed (BACKLOG B10 #3).
  const recent = useQuery({
    queryKey: ['queries', 'recent'],
    queryFn: () => client.listQueries({ limit: 6 }),
    retry: false,
    refetchInterval: 30_000,
  });
  const recentItems = recent.data?.items ?? [];

  const faith = latestRun.data?.summary.faithfulness_avg ?? null;
  const runningCount = (jobs.data ?? []).filter((j) => RUNNING.has(j.status)).length;

  const series = metrics.data?.series ?? [];
  const queriesSeries = series.map((b) => b.queries);
  const p95Series = series.map((b) => b.p95_latency_ms).filter((v): v is number => v !== null);
  const p95 = metrics.data?.latency.p95_ms ?? null;
  const totalQueries = metrics.data?.total_queries ?? null;
  const p95Tone: Tone =
    p95 === null ? 'neutral' : p95 >= 600 ? 'danger' : p95 >= 300 ? 'warning' : 'success';

  const cost = usage.data?.total_cost_usd ?? null;
  const costUtil = usage.data?.budget_utilization_pct ?? null;
  const costLimit = usage.data?.budget?.limit_usd ?? null;
  const costSeries = (usage.data?.series ?? []).map((b) => b.cost_usd);
  const costTone: Tone =
    costUtil === null
      ? 'neutral'
      : costUtil >= 100
        ? 'danger'
        : costUtil >= 80
          ? 'warning'
          : 'success';
  const costSub =
    costUtil !== null && costLimit !== null
      ? `${Math.round(costUtil)}% of $${costLimit.toFixed(0)} budget`
      : cost !== null
        ? 'no budget set'
        : 'month-to-date';

  return (
    <div>
      <PageHeader
        title="Dashboard"
        description="Tenant health, ingestion pipeline, and evaluation signal."
        actions={
          <>
            <button
              type="button"
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background px-3 text-[13px] font-medium"
            >
              <Clock className="h-3.5 w-3.5" /> Last 24h
            </button>
            <button
              type="button"
              onClick={() => qc.invalidateQueries()}
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background px-3 text-[13px] font-medium transition-colors hover:bg-muted"
            >
              <RefreshCw className="h-3.5 w-3.5" /> Refresh
            </button>
            <Link
              href="/query-playground"
              className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-[13px] font-medium text-primary-foreground transition-colors hover:bg-primary/90"
            >
              <Sparkles className="h-3.5 w-3.5" /> Run query
            </Link>
          </>
        }
      />

      {/* ops vitals — real per-tenant signal: queries/p95 (ADR-0038), cost (ADR-0039) */}
      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricTile
          label="Queries · 24h"
          value={totalQueries ?? '—'}
          sub="last 24 hours"
          tone="success"
          spark={queriesSeries}
        />
        <MetricTile
          label="p95 latency"
          value={p95 !== null ? `${Math.round(p95)} ms` : '—'}
          sub={p95 !== null ? 'wall clock · 24h' : 'no queries yet'}
          tone={p95Tone}
          spark={p95Series}
        />
        <MetricTile
          label="Cost · MTD"
          value={cost !== null ? `$${cost.toFixed(2)}` : '—'}
          sub={costSub}
          tone={costTone}
          spark={costSeries}
        />
        <MetricTile
          label="Faithfulness · latest"
          value={faith !== null ? formatNumber(faith, 2) : '—'}
          sub={faith !== null ? 'ragas · most recent run' : 'no completed run yet'}
          tone={faith !== null ? scoreTone(faith, 0.85) : 'neutral'}
        />
      </div>

      {/* pipeline + recent queries */}
      <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Card className="overflow-hidden">
          <PanelHeader
            title="Ingestion pipeline"
            sub="Temporal workflows · newest collection"
            right={
              runningCount > 0 ? (
                <Badge variant="info" dot pulse>
                  {runningCount} running
                </Badge>
              ) : (
                <Badge variant="secondary">idle</Badge>
              )
            }
          />
          <div className="py-1">
            {!firstCollectionId && (
              <EmptyRow text="No collections yet — create one to start ingesting." />
            )}
            {firstCollectionId && jobs.isLoading && <EmptyRow text="Loading workflows…" />}
            {firstCollectionId && jobs.data && jobs.data.length === 0 && (
              <EmptyRow text="No ingestion runs for this collection yet." />
            )}
            {jobs.data?.slice(0, 6).map((job, i, arr) => (
              <PipelineRow key={job.id} job={job} last={i === arr.length - 1} />
            ))}
          </div>
        </Card>

        <Card className="overflow-hidden">
          <PanelHeader
            title="Recent queries"
            right={
              <Link
                href="/query-playground"
                className="inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
              >
                Playground <ArrowRight className="h-3 w-3" />
              </Link>
            }
          />
          {recentItems.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
              <div className="grid h-10 w-10 place-items-center rounded-lg bg-muted">
                <Sparkles className="h-4 w-4 text-muted-foreground" />
              </div>
              <div className="text-sm font-medium">
                {recent.isLoading ? 'Loading queries…' : 'No queries yet'}
              </div>
              <p className="max-w-xs text-[13px] text-muted-foreground">
                Run a query in the Playground to see its answer, grounding, and trace here.
              </p>
            </div>
          ) : (
            <div className="py-1">
              {recentItems.map((q, i, arr) => (
                <RecentQueryRow key={q.id} q={q} last={i === arr.length - 1} />
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* pillars */}
      <Card className="p-4">
        <div className="mb-3 flex items-center justify-between">
          <SectionLabel>architectural pillars · enforced across services</SectionLabel>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {PILLARS.map((p) => {
            const Icon = p.icon;
            return (
              <div
                key={p.title}
                className="flex gap-3 rounded-md border border-border bg-background p-3"
              >
                <div className="grid h-[30px] w-[30px] shrink-0 place-items-center rounded-md bg-muted">
                  <Icon className="h-4 w-4" strokeWidth={1.75} />
                </div>
                <div className="min-w-0">
                  <div className="text-[13px] font-medium">{p.title}</div>
                  <div className="mt-0.5 text-xs leading-4 text-muted-foreground">{p.desc}</div>
                </div>
              </div>
            );
          })}
        </div>
      </Card>
    </div>
  );
}

function MetricTile({
  label,
  value,
  sub,
  tone = 'neutral',
  spark,
}: {
  label: string;
  value: ReactNode;
  sub: ReactNode;
  tone?: Tone;
  spark?: number[];
}) {
  return (
    <Card className="flex min-h-[108px] flex-col gap-2 p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="truncate text-[26px] font-semibold leading-none tracking-tight">{value}</div>
      <div className="mt-auto flex items-end justify-between gap-2">
        <div
          className="text-xs"
          style={{ color: tone === 'neutral' ? undefined : toneColor[tone] }}
        >
          {sub}
        </div>
        {spark && spark.length >= 2 && (
          <MiniSpark data={spark} w={84} h={26} stroke={toneColor[tone]} fill={toneColor[tone]} />
        )}
      </div>
    </Card>
  );
}

function PanelHeader({
  title,
  sub,
  right,
}: {
  title: string;
  sub?: string;
  right?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3.5">
      <div className="min-w-0">
        <div className="text-sm font-semibold tracking-tight">{title}</div>
        {sub && <div className="mt-0.5 text-xs text-muted-foreground">{sub}</div>}
      </div>
      {right}
    </div>
  );
}

function EmptyRow({ text }: { text: string }) {
  return <div className="px-4 py-6 text-center text-[13px] text-muted-foreground">{text}</div>;
}

function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const s = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

function RecentQueryRow({ q, last }: { q: QuerySessionListItem; last: boolean }) {
  return (
    <div
      className={cn(
        'grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-4 py-2.5',
        last ? '' : 'border-b border-border',
      )}
    >
      <div className="min-w-0">
        <div className="mb-1 flex items-center gap-2">
          <Mono dim>{q.id.slice(0, 8)}</Mono>
          <span className="text-[11px] text-muted-foreground">· {timeAgo(q.created_at)} ago</span>
          {q.status === 'abstained' && (
            <Badge variant="warning" className="text-[10px]">
              abstain
            </Badge>
          )}
          {q.status === 'failed' && (
            <Badge variant="destructive" className="text-[10px]">
              failed
            </Badge>
          )}
        </div>
        <div className="truncate text-[13px]">{q.query}</div>
      </div>
      <div className="flex items-center gap-2 self-center">
        {q.grounding_score !== null ? (
          <Badge
            variant={toneBadgeVariant[scoreTone(q.grounding_score, 0.85)]}
            className="font-mono"
          >
            {q.grounding_score.toFixed(2)}
          </Badge>
        ) : (
          <Badge variant="secondary" className="font-mono">
            —
          </Badge>
        )}
        {q.latency_ms !== null && <Mono dim>{q.latency_ms}ms</Mono>}
      </div>
    </div>
  );
}

function PipelineRow({ job, last }: { job: IngestionJob; last: boolean }) {
  const tone = statusTone(job.status);
  const pct =
    job.documents_total > 0
      ? job.documents_processed / job.documents_total
      : job.status === 'completed'
        ? 1
        : 0;
  return (
    <div
      className={`grid grid-cols-[80px_minmax(0,1fr)_104px] items-center gap-3 px-4 py-2.5 sm:grid-cols-[80px_minmax(0,1fr)_104px_96px] ${
        last ? '' : 'border-b border-border'
      }`}
    >
      <Mono dim>{job.id.slice(0, 8)}</Mono>
      <div className="min-w-0">
        <div className="truncate text-[13px]">{job.workflow_id ?? job.chunking_strategy}</div>
        <div className="mt-1.5 flex items-center gap-2">
          <DataBar value={pct} color={toneColor[tone]} />
          <Mono dim>{Math.round(pct * 100)}%</Mono>
        </div>
      </div>
      <Badge variant={toneBadgeVariant[tone]} dot pulse={job.status === 'processing'}>
        {job.status}
      </Badge>
      <Mono dim className="hidden truncate sm:block">
        {job.embedding_model}
      </Mono>
    </div>
  );
}
