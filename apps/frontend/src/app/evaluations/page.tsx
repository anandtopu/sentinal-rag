'use client';

import { useQuery } from '@tanstack/react-query';
import { Download, Filter, Play } from 'lucide-react';

import { PageHeader } from '@/components/layout/page-header';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { DataBar } from '@/components/ui/data-bar';
import { Mono } from '@/components/ui/mono';
import { SectionLabel } from '@/components/ui/section-label';
import { MiniSpark, TrendSpark } from '@/components/ui/spark';
import type { EvaluationRun, EvaluationScoreSummary } from '@/lib/api-types';
import { scoreTone, statusTone, toneBadgeVariant, toneColor } from '@/lib/tone';
import { useApiClient } from '@/lib/use-api-client';
import { formatDateTime, formatNumber } from '@/lib/utils';

type MetricKey = keyof Pick<
  EvaluationScoreSummary,
  'faithfulness_avg' | 'answer_correctness_avg' | 'context_relevance_avg' | 'citation_accuracy_avg'
>;

const METRICS: { key: MetricKey; label: string; short: string; thresh: number }[] = [
  { key: 'faithfulness_avg', label: 'Faithfulness · median', short: 'faith', thresh: 0.85 },
  {
    key: 'answer_correctness_avg',
    label: 'Answer correctness · median',
    short: 'ans',
    thresh: 0.85,
  },
  { key: 'context_relevance_avg', label: 'Context relevance · median', short: 'ctx', thresh: 0.75 },
  {
    key: 'citation_accuracy_avg',
    label: 'Citation accuracy · median',
    short: 'cite',
    thresh: 0.92,
  },
];

function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

export default function EvaluationsPage() {
  const { client } = useApiClient();
  // One batched call carries every run + its live-aggregated summary, so the
  // leaderboard / medians / trend load without an N+1 fan-out (ADR-0040).
  const runsQuery = useQuery({
    queryKey: ['eval-runs', 'summary'],
    queryFn: () => client.listEvalRuns({ includeSummary: true }),
  });

  const runs = [...(runsQuery.data ?? [])].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );
  const runsAsc = [...runs].reverse();

  const seriesFor = (key: MetricKey) =>
    runsAsc.map((r) => r.summary?.[key]).filter((v): v is number => v !== null && v !== undefined);
  const medianFor = (key: MetricKey) =>
    median(
      runs.map((r) => r.summary?.[key]).filter((v): v is number => v !== null && v !== undefined),
    );

  const latestSummary = runs
    .map((r) => r.summary)
    .find((s): s is EvaluationScoreSummary => Boolean(s));

  return (
    <div>
      <PageHeader
        title="Evaluations"
        description="ragas + custom evaluators on golden datasets. Each run pins prompt version + model + dataset."
        actions={
          <>
            <Button variant="outline" size="sm">
              <Filter className="h-3.5 w-3.5" /> Filters
            </Button>
            <Button variant="outline" size="sm">
              <Download className="h-3.5 w-3.5" /> Export CSV
            </Button>
            <Button size="sm">
              <Play className="h-3.5 w-3.5" /> New run
            </Button>
          </>
        }
      />

      {/* metric overview */}
      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {METRICS.map((m) => {
          const value = medianFor(m.key);
          const tone = value !== null ? scoreTone(value, m.thresh) : 'neutral';
          return (
            <Card key={m.key} className="p-4">
              <div className="text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
                {m.label}
              </div>
              <div className="mt-2 font-mono text-2xl font-semibold tracking-tight">
                {value !== null ? formatNumber(value, 2) : '—'}
              </div>
              <div className="mt-1.5">
                <MiniSpark
                  data={seriesFor(m.key)}
                  w={224}
                  h={26}
                  stroke={toneColor[tone]}
                  fill={toneColor[tone]}
                />
              </div>
            </Card>
          );
        })}
      </div>

      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[1.4fr_1fr]">
        {/* leaderboard */}
        <Card className="overflow-hidden">
          <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3.5">
            <div>
              <div className="text-sm font-semibold tracking-tight">Recent runs</div>
              <div className="mt-0.5 text-xs text-muted-foreground">
                Comparison view · each run pins prompt version + model + dataset.
              </div>
            </div>
          </div>
          <div className="overflow-x-auto">
            <div className="min-w-[600px]">
              <div className="grid grid-cols-[76px_minmax(150px,1fr)_56px_56px_56px_56px_72px] items-center gap-2 border-b border-border px-4 py-2 font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
                <span>run</span>
                <span>config</span>
                {METRICS.map((m) => (
                  <span key={m.key} className="text-right">
                    {m.short}
                  </span>
                ))}
                <span className="text-right">status</span>
              </div>
              {runs.map((r, i) => (
                <EvalRow key={r.id} run={r} summary={r.summary ?? null} latest={i === 0} />
              ))}
              {!runs.length && (
                <div className="px-4 py-8 text-center text-[13px] text-muted-foreground">
                  {runsQuery.isLoading
                    ? 'Loading…'
                    : 'No evaluation runs yet. Trigger one via POST /api/v1/eval/runs.'}
                </div>
              )}
            </div>
          </div>
        </Card>

        {/* trend + case outcomes */}
        <div className="flex flex-col gap-3">
          <Card className="p-4">
            <div className="mb-2.5 flex items-center justify-between">
              <div>
                <div className="text-[13px] font-semibold">Faithfulness · trend</div>
                <div className="mt-0.5 text-xs text-muted-foreground">Threshold 0.85</div>
              </div>
              {medianFor('faithfulness_avg') !== null && (
                <Badge variant="success" className="font-mono">
                  {formatNumber(medianFor('faithfulness_avg'), 2)}
                </Badge>
              )}
            </div>
            <TrendSpark
              data={seriesFor('faithfulness_avg')}
              min={0.75}
              max={1}
              threshold={0.85}
              stroke={toneColor.success}
            />
          </Card>

          <Card className="p-4">
            <SectionLabel className="mb-2.5">case outcomes · latest run</SectionLabel>
            {latestSummary ? (
              <CaseOutcomes summary={latestSummary} />
            ) : (
              <div className="py-3 text-center text-[13px] text-muted-foreground">
                No completed run with persisted results yet.
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function EvalRow({
  run,
  summary,
  latest,
}: {
  run: EvaluationRun;
  summary: EvaluationScoreSummary | null;
  latest: boolean;
}) {
  const tone = statusTone(run.status);
  return (
    <div
      className={`grid grid-cols-[76px_minmax(150px,1fr)_56px_56px_56px_56px_72px] items-center gap-2 border-b border-border px-4 py-2.5 ${
        latest ? 'bg-success/[0.04]' : ''
      }`}
    >
      <Mono dim>{run.id.slice(0, 8)}</Mono>
      <div className="flex min-w-0 items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{run.name}</span>
        {latest && (
          <Badge variant="info" dot pulse className="shrink-0 text-[10px]">
            latest
          </Badge>
        )}
      </div>
      {METRICS.map((m) => (
        <MetricCell key={m.key} value={summary?.[m.key] ?? null} thresh={m.thresh} />
      ))}
      <div className="text-right">
        <Badge variant={toneBadgeVariant[tone]} dot pulse={run.status === 'running'}>
          {run.status}
        </Badge>
      </div>
    </div>
  );
}

function MetricCell({ value, thresh }: { value: number | null; thresh: number }) {
  if (value === null) {
    return (
      <Mono dim className="block text-right">
        —
      </Mono>
    );
  }
  const ok = value >= thresh;
  return (
    <span
      className="block text-right font-mono text-xs"
      style={{ color: ok ? undefined : toneColor.warning }}
    >
      {formatNumber(value, 2)}
    </span>
  );
}

function CaseOutcomes({ summary }: { summary: EvaluationScoreSummary }) {
  const total = summary.cases_total || 1;
  const rows = [
    { k: 'completed', n: summary.cases_completed, tone: 'success' as const },
    { k: 'failed', n: summary.cases_failed, tone: 'danger' as const },
  ];
  return (
    <div className="flex flex-col gap-2.5">
      {rows.map((r) => (
        <div key={r.k} className="grid grid-cols-[1fr_40px_88px] items-center gap-2">
          <div className="text-xs">{r.k}</div>
          <Mono>{r.n}</Mono>
          <DataBar value={r.n} max={total} color={toneColor[r.tone]} />
        </div>
      ))}
      <div className="text-[11px] text-muted-foreground">
        {summary.cases_total} cases · {formatNumber(summary.average_latency_ms, 0)} ms avg
      </div>
    </div>
  );
}
