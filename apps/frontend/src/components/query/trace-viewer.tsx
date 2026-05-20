'use client';

import { useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { DataBar } from '@/components/ui/data-bar';
import { Mono } from '@/components/ui/mono';
import type { GeneratedAnswerSummary, RetrievalResultRead } from '@/lib/api-types';
import { type Tone, scoreTone, toneBadgeVariant, toneColor, verdictTone } from '@/lib/tone';
import { useApiClient } from '@/lib/use-api-client';
import { useTraceStream } from '@/lib/use-trace-stream';
import { formatNumber } from '@/lib/utils';

// Canonical pipeline order; unknown stages append in arrival order.
const STAGE_ORDER = ['bm25', 'vector', 'hybrid_merge', 'rerank'];

const TABS = [
  { id: 'pipeline', label: 'Pipeline' },
  { id: 'results', label: 'Results' },
  { id: 'raw', label: 'Raw JSON' },
] as const;
type TabId = (typeof TABS)[number]['id'];

function groupByStage(rows: RetrievalResultRead[]): Record<string, RetrievalResultRead[]> {
  const out: Record<string, RetrievalResultRead[]> = {};
  for (const r of rows) {
    if (!out[r.stage]) out[r.stage] = [];
    out[r.stage].push(r);
  }
  return out;
}

function orderedStages(byStage: Record<string, RetrievalResultRead[]>): string[] {
  return STAGE_ORDER.filter((s) => byStage[s]).concat(
    Object.keys(byStage).filter((s) => !STAGE_ORDER.includes(s)),
  );
}

export function TraceViewer({ querySessionId }: { querySessionId: string }) {
  const { token } = useApiClient();
  const { data, error, transport, isStreaming } = useTraceStream(querySessionId, token);
  const [tab, setTab] = useState<TabId>('pipeline');

  if (error && !data) {
    return <Card className="p-4 text-sm text-destructive">{error.message}</Card>;
  }
  if (!data) {
    return <Card className="p-4 text-sm text-muted-foreground">Loading trace…</Card>;
  }

  const byStage = groupByStage(data.retrieval_results);
  const stages = orderedStages(byStage);

  return (
    <Card className="overflow-hidden">
      {/* header */}
      <div className="flex flex-wrap items-center gap-3 border-b border-border p-4">
        <h2 className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
          trace
        </h2>
        <Mono dim>{querySessionId.slice(0, 8)}…</Mono>
        <div className="flex-1" />
        <Badge variant="outline" className="font-mono">
          {data.status}
        </Badge>
        {data.latency_ms !== null && (
          <Badge variant="outline" className="font-mono">
            {data.latency_ms} ms
          </Badge>
        )}
        {isStreaming && (
          <Badge variant="secondary" dot pulse title={`live via ${transport}`}>
            live · {transport}
          </Badge>
        )}
      </div>

      {/* tabs */}
      <div className="flex items-center gap-1 border-b border-border px-3 py-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={
              tab === t.id
                ? 'rounded-md bg-muted px-2.5 py-1 text-[13px] font-medium text-foreground'
                : 'rounded-md px-2.5 py-1 text-[13px] text-muted-foreground transition-colors hover:text-foreground'
            }
          >
            {t.label}
          </button>
        ))}
        <div className="flex-1" />
        <Mono dim className="hidden sm:inline">
          total {data.latency_ms ?? '—'} ms · {stages.length} stages
        </Mono>
      </div>

      <div className="p-4">
        {tab === 'pipeline' && (
          <PipelineView stages={stages} byStage={byStage} generation={data.generation} />
        )}
        {tab === 'results' && <ResultsView stages={stages} byStage={byStage} />}
        {tab === 'raw' && (
          <pre className="max-h-[420px] overflow-auto rounded-md bg-muted p-3 font-mono text-[11px] leading-relaxed">
            {JSON.stringify(data, null, 2)}
          </pre>
        )}
      </div>
    </Card>
  );
}

function PipelineView({
  stages,
  byStage,
  generation,
}: {
  stages: string[];
  byStage: Record<string, RetrievalResultRead[]>;
  generation: GeneratedAnswerSummary | null;
}) {
  const maxCount = Math.max(1, ...stages.map((s) => byStage[s].length));
  const grounding = generation?.grounding_score ?? null;
  const nli = generation?.nli_verdict ?? null;
  const judge = generation?.judge_verdict ?? null;

  return (
    <div className="space-y-5">
      <div>
        <div className="mb-3 font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
          retrieval pipeline · waterfall
        </div>
        {/* Per-stage timing isn't captured in the trace; bars are sized by
            result count (real) and the header carries the real total latency. */}
        <div>
          {stages.map((s, i) => {
            const rows = byStage[s];
            const count = rows.length;
            const top = Math.max(...rows.map((r) => r.score));
            const tone: Tone = s === 'rerank' ? 'success' : 'info';
            return (
              <div
                key={s}
                className={`grid grid-cols-[110px_minmax(0,1fr)_72px] items-center gap-3 py-2 ${
                  i === 0 ? '' : 'border-t border-dashed border-border'
                }`}
              >
                <div className="min-w-0">
                  <div className="truncate text-[13px] font-medium">{s}</div>
                  <div className="truncate text-[11px] text-muted-foreground">
                    top {formatNumber(top, 3)}
                  </div>
                </div>
                <DataBar value={count} max={maxCount} color={toneColor[tone]} height={14} />
                <Mono className="text-right">{count} results</Mono>
              </div>
            );
          })}
        </div>
      </div>

      <div>
        <div className="mb-3 font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
          hallucination cascade · 3-layer
        </div>
        <div className="grid gap-2.5 sm:grid-cols-3">
          <CascadeCard
            label="Overlap (token f1)"
            value={grounding !== null ? formatNumber(grounding, 2) : 'off'}
            tone={grounding !== null ? scoreTone(grounding) : 'neutral'}
            sub="≥ 0.75 — claim/source overlap"
            verdict={grounding !== null ? (grounding >= 0.75 ? 'pass' : 'review') : 'not run'}
          />
          <CascadeCard
            label="NLI (deberta-v3)"
            value={nli ?? 'off'}
            tone={verdictTone(nli)}
            sub="entailment over extracted claims"
            verdict={nli ?? 'not run'}
          />
          <CascadeCard
            label="LLM judge"
            value={judge ?? 'off'}
            tone={verdictTone(judge)}
            sub="grounded · citations correct · sampled"
            verdict={judge ?? 'not run'}
          />
        </div>
      </div>
    </div>
  );
}

function CascadeCard({
  label,
  value,
  sub,
  verdict,
  tone,
}: {
  label: string;
  value: string;
  sub: string;
  verdict: string;
  tone: Tone;
}) {
  return (
    <div
      className="rounded-md border border-border bg-background p-3"
      style={{ borderLeft: `3px solid ${toneColor[tone]}` }}
    >
      <div className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
        {label}
      </div>
      <div
        className="mt-2 font-mono text-base font-semibold"
        style={{ color: tone === 'neutral' ? undefined : toneColor[tone] }}
      >
        {value}
      </div>
      <div className="mt-1 text-xs leading-4 text-muted-foreground">{sub}</div>
      <div className="mt-2.5">
        <Badge variant={toneBadgeVariant[tone]} dot>
          {verdict}
        </Badge>
      </div>
    </div>
  );
}

function ResultsView({
  stages,
  byStage,
}: {
  stages: string[];
  byStage: Record<string, RetrievalResultRead[]>;
}) {
  return (
    <div className="space-y-4">
      {stages.map((stage) => (
        <div key={stage}>
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
            <Badge variant="secondary">{stage}</Badge>
            <span className="text-muted-foreground">{byStage[stage].length} results</span>
          </div>
          <ol className="space-y-1 text-xs">
            {byStage[stage].slice(0, 8).map((r) => (
              <li
                key={`${stage}-${r.rank}-${r.chunk_id}`}
                className="flex items-center gap-3 rounded-md border border-border px-2 py-1"
              >
                <span className="w-6 text-right text-muted-foreground">#{r.rank}</span>
                <Mono>{r.chunk_id.slice(0, 8)}</Mono>
                <span className="ml-auto text-muted-foreground">
                  score {formatNumber(r.score, 4)}
                </span>
              </li>
            ))}
          </ol>
        </div>
      ))}
    </div>
  );
}
