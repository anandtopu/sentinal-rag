'use client';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import type { RetrievalResultRead } from '@/lib/api-types';
import { useApiClient } from '@/lib/use-api-client';
import { useTraceStream } from '@/lib/use-trace-stream';
import { formatNumber } from '@/lib/utils';

function groupByStage(rows: RetrievalResultRead[]): Record<string, RetrievalResultRead[]> {
  const out: Record<string, RetrievalResultRead[]> = {};
  for (const r of rows) {
    if (!out[r.stage]) out[r.stage] = [];
    out[r.stage].push(r);
  }
  return out;
}

const STAGE_ORDER = ['bm25', 'vector', 'hybrid_merge', 'rerank'];

type CascadeTone = 'good' | 'warn' | 'bad' | 'muted';

function overlapTone(score: number | null | undefined): CascadeTone {
  if (score === null || score === undefined) return 'muted';
  if (score >= 0.7) return 'good';
  if (score >= 0.4) return 'warn';
  return 'bad';
}

function verdictTone(verdict: string | null | undefined): CascadeTone {
  if (!verdict) return 'muted';
  if (verdict === 'entail' || verdict === 'pass') return 'good';
  if (verdict === 'neutral' || verdict === 'skipped') return 'warn';
  if (verdict === 'contradict' || verdict === 'fail') return 'bad';
  return 'muted';
}

function CascadeLayer({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: CascadeTone;
}) {
  const variant: 'default' | 'secondary' | 'destructive' | 'outline' =
    tone === 'good'
      ? 'default'
      : tone === 'bad'
        ? 'destructive'
        : tone === 'warn'
          ? 'secondary'
          : 'outline';
  return (
    <div className="rounded border border-border px-3 py-2">
      <div className="text-xs uppercase text-muted-foreground">{label}</div>
      <Badge variant={variant} className="mt-1 font-mono text-xs">
        {value}
      </Badge>
    </div>
  );
}

export function TraceViewer({ querySessionId }: { querySessionId: string }) {
  const { token } = useApiClient();
  const { data, error, transport, isStreaming } = useTraceStream(querySessionId, token);

  if (error && !data) {
    return <p className="text-sm text-destructive">{error.message}</p>;
  }
  if (!data) return <p className="text-sm text-muted-foreground">Loading trace…</p>;

  const byStage = groupByStage(data.retrieval_results);
  const stages = STAGE_ORDER.filter((s) => byStage[s]).concat(
    Object.keys(byStage).filter((s) => !STAGE_ORDER.includes(s)),
  );

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Trace</CardTitle>
            <CardDescription>
              <code>{querySessionId.slice(0, 8)}…</code> — every retrieval stage and the generation
              persisted for audit.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <Badge variant="outline">{data.status}</Badge>
            {data.latency_ms !== null && <Badge variant="outline">{data.latency_ms} ms</Badge>}
            {isStreaming && (
              <Badge variant="secondary" title={`live via ${transport}`}>
                {transport === 'sse' ? 'live (sse)' : 'live (poll)'}
              </Badge>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {data.generation && (
          <>
            <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
              <div>
                <div className="text-xs uppercase text-muted-foreground">Model</div>
                <div className="font-mono text-xs">{data.generation.model}</div>
              </div>
              <div>
                <div className="text-xs uppercase text-muted-foreground">Tokens (in/out)</div>
                <div>
                  {data.generation.input_tokens ?? '—'} / {data.generation.output_tokens ?? '—'}
                </div>
              </div>
              <div>
                <div className="text-xs uppercase text-muted-foreground">Cost (USD)</div>
                <div>{formatNumber(data.generation.cost_usd, 5)}</div>
              </div>
              <div>
                <div className="text-xs uppercase text-muted-foreground">Grounding</div>
                <div>{formatNumber(data.generation.grounding_score, 3)}</div>
              </div>
            </div>

            <div>
              <h3 className="mb-2 text-sm font-semibold">Hallucination cascade</h3>
              <div className="grid grid-cols-3 gap-3 text-sm">
                <CascadeLayer
                  label="Overlap"
                  value={formatNumber(data.generation.grounding_score, 3)}
                  tone={overlapTone(data.generation.grounding_score)}
                />
                <CascadeLayer
                  label="NLI"
                  value={data.generation.nli_verdict ?? 'off'}
                  tone={verdictTone(data.generation.nli_verdict)}
                />
                <CascadeLayer
                  label="Judge"
                  value={data.generation.judge_verdict ?? 'off'}
                  tone={verdictTone(data.generation.judge_verdict)}
                />
              </div>
            </div>
          </>
        )}

        {stages.map((stage) => (
          <div key={stage}>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
              <Badge variant="secondary">{stage}</Badge>
              <span className="text-muted-foreground">{byStage[stage].length} results</span>
            </h3>
            <ol className="space-y-1 text-xs">
              {byStage[stage].slice(0, 8).map((r) => (
                <li
                  key={`${stage}-${r.rank}-${r.chunk_id}`}
                  className="flex items-center gap-3 rounded border border-border px-2 py-1"
                >
                  <span className="w-6 text-right text-muted-foreground">#{r.rank}</span>
                  <span className="font-mono">{r.chunk_id.slice(0, 8)}</span>
                  <span className="ml-auto text-muted-foreground">
                    score {formatNumber(r.score, 4)}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
