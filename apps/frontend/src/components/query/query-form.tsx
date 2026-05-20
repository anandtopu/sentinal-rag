'use client';

import { useMutation, useQuery } from '@tanstack/react-query';
import {
  Bookmark,
  ChevronDown,
  Copy,
  Download,
  Link2,
  MoreHorizontal,
  Play,
  Sparkles,
} from 'lucide-react';
import { useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Kbd, Mono } from '@/components/ui/mono';
import { Pill } from '@/components/ui/pill';
import { SectionLabel } from '@/components/ui/section-label';
import { Textarea } from '@/components/ui/textarea';
import type { CitationRead, QueryRequest, QueryResponse } from '@/lib/api-types';
import { type Tone, scoreTone, toneBadgeVariant, verdictTone } from '@/lib/tone';
import { useApiClient } from '@/lib/use-api-client';
import { cn, formatNumber } from '@/lib/utils';

import { TraceViewer } from './trace-viewer';

const MAX_CHARS = 4096;

export function QueryForm() {
  const { client } = useApiClient();
  const [query, setQuery] = useState('');
  const [collectionIds, setCollectionIds] = useState<string[]>([]);
  const [model, setModel] = useState('ollama/llama3.1:8b');
  const [temperature, setTemperature] = useState(0.2);
  const [topK, setTopK] = useState(8);
  const [mode, setMode] = useState<'hybrid' | 'bm25' | 'vector'>('hybrid');
  const [includeCitations, setIncludeCitations] = useState(true);
  const [abstain, setAbstain] = useState(true);
  const [showTrace, setShowTrace] = useState(true);
  const [result, setResult] = useState<QueryResponse | null>(null);

  const collections = useQuery({
    queryKey: ['collections'],
    queryFn: () => client.listCollections({ limit: 200 }),
  });
  const prompts = useQuery({
    queryKey: ['prompts'],
    queryFn: () => client.listPrompts(),
    retry: false,
  });

  const exec = useMutation({
    mutationFn: (payload: QueryRequest) => client.executeQuery(payload),
    onSuccess: (resp) => setResult(resp),
  });

  const totalChunks = collections.data?.items.length ?? 0;
  const defaultPrompt = prompts.data?.[0];

  function submit() {
    if (!query.trim() || collectionIds.length === 0) return;
    exec.mutate({
      query,
      collection_ids: collectionIds,
      retrieval: { mode, top_k_rerank: topK },
      generation: { model, temperature },
      options: {
        include_citations: includeCitations,
        include_debug_trace: true,
        abstain_if_unsupported: abstain,
      },
    });
  }

  return (
    <div className="space-y-4">
      {/* header strip */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            {result ? (
              <>
                <Mono dim>session</Mono>
                <Mono>{result.query_session_id}</Mono>
                <Badge variant="success" dot pulse className="font-mono">
                  sse · live
                </Badge>
              </>
            ) : (
              <Mono dim>no active session — compose a query to begin</Mono>
            )}
          </div>
          <h1 className="text-[22px] font-semibold tracking-tight">Query Playground</h1>
        </div>
        <div className="flex items-center gap-1.5">
          <Button variant="outline" size="sm" disabled={!result}>
            <Bookmark className="h-3.5 w-3.5" /> Save query
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!result}
            onClick={() => result && downloadJson(result, `query-${result.query_session_id}.json`)}
          >
            <Download className="h-3.5 w-3.5" /> Export trace
          </Button>
          <Button variant="outline" size="icon" className="h-8 w-8" aria-label="More">
            <MoreHorizontal className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* body */}
      <div className="grid items-start gap-4 lg:grid-cols-[380px_minmax(0,1fr)]">
        {/* composer */}
        <Card className="lg:sticky lg:top-0">
          <div className="border-b border-border p-4">
            <SectionLabel className="mb-1.5">compose · /query</SectionLabel>
            <p className="text-[13px] text-muted-foreground">
              Hybrid retrieval → reranker → llm, with full trace.
            </p>
          </div>

          <form
            className="flex flex-col gap-3.5 p-4"
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
          >
            <Field
              label="Question"
              htmlFor="q"
              right={
                <span className="text-[11px] text-muted-foreground">
                  {query.length} / {MAX_CHARS}
                </span>
              }
            >
              <Textarea
                id="q"
                value={query}
                maxLength={MAX_CHARS}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                    e.preventDefault();
                    submit();
                  }
                }}
                placeholder="What does the runbook say about pgvector index rebuilds — when are they triggered, and what's the rollback?"
                rows={4}
              />
            </Field>

            <Field
              label="Collections"
              right={
                <span className="text-[11px] text-muted-foreground">
                  {collectionIds.length} selected
                </span>
              }
            >
              <div className="flex flex-wrap gap-1.5">
                {collections.data?.items.map((c) => {
                  const selected = collectionIds.includes(c.id);
                  return (
                    <Pill
                      key={c.id}
                      pressed={selected}
                      onClick={() =>
                        setCollectionIds((prev) =>
                          prev.includes(c.id) ? prev.filter((x) => x !== c.id) : [...prev, c.id],
                        )
                      }
                    >
                      {c.name}
                    </Pill>
                  );
                })}
                {collections.isLoading && (
                  <span className="text-[11px] text-muted-foreground">Loading collections…</span>
                )}
                {collections.data && totalChunks === 0 && (
                  <span className="text-[11px] text-muted-foreground">
                    No collections — create one first.
                  </span>
                )}
              </div>
            </Field>

            <div className="grid grid-cols-2 gap-2.5">
              <Field label="Model" htmlFor="model">
                <Input
                  id="model"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  className="h-8 font-mono text-[13px]"
                />
              </Field>
              <Field label="Temperature" htmlFor="temperature">
                <Input
                  id="temperature"
                  type="number"
                  min={0}
                  max={2}
                  step={0.1}
                  value={temperature}
                  onChange={(e) => setTemperature(Number.parseFloat(e.target.value) || 0)}
                  className="h-8 font-mono text-[13px]"
                />
              </Field>
              <Field label="Top-k rerank" htmlFor="topk">
                <Input
                  id="topk"
                  type="number"
                  min={1}
                  max={50}
                  value={topK}
                  onChange={(e) => setTopK(Number.parseInt(e.target.value, 10) || 8)}
                  className="h-8 font-mono text-[13px]"
                />
              </Field>
              <Field label="Mode" htmlFor="mode">
                <div className="relative">
                  <select
                    id="mode"
                    value={mode}
                    onChange={(e) => setMode(e.target.value as typeof mode)}
                    className="h-8 w-full appearance-none rounded-md border border-input bg-background px-2.5 pr-7 font-mono text-[13px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <option value="hybrid">hybrid</option>
                    <option value="bm25">bm25 only</option>
                    <option value="vector">vector only</option>
                  </select>
                  <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
                </div>
              </Field>
            </div>

            <div className="flex flex-col gap-2 rounded-md bg-muted p-3">
              <ToggleRow
                checked={includeCitations}
                onChange={setIncludeCitations}
                label="Include citations"
              />
              <ToggleRow
                checked={abstain}
                onChange={setAbstain}
                label="Abstain if unsupported (grounding < 0.5)"
              />
              <ToggleRow checked={showTrace} onChange={setShowTrace} label="Show stage trace" />
            </div>

            {/* prompt pin — informational; backend resolves the default version */}
            <div className="flex items-center gap-2 rounded-md border border-dashed border-border px-3 py-2.5">
              <Bookmark className="h-3.5 w-3.5 text-muted-foreground" />
              <div className="flex-1 text-xs">
                <span className="text-muted-foreground">prompt</span>{' '}
                {defaultPrompt ? (
                  <>
                    <Mono>{defaultPrompt.name}</Mono>
                    <span className="text-muted-foreground"> · </span>
                    <Mono>default</Mono>
                  </>
                ) : (
                  <Mono dim>resolved at run time</Mono>
                )}
              </div>
            </div>

            {exec.error && (
              <p className="text-sm text-destructive">{(exec.error as Error).message}</p>
            )}

            <div className="flex items-center gap-2">
              <Button
                type="submit"
                size="lg"
                className="flex-1"
                disabled={exec.isPending || !query.trim() || collectionIds.length === 0}
              >
                <Play className="h-3.5 w-3.5" />
                {exec.isPending ? 'Running…' : 'Run query'}
              </Button>
              <Kbd>⌘↵</Kbd>
            </div>
          </form>
        </Card>

        {/* answer + trace */}
        <div className="flex min-w-0 flex-col gap-4">
          {result ? (
            <>
              <AnswerPanel result={result} />
              {showTrace && <TraceViewer querySessionId={result.query_session_id} />}
            </>
          ) : (
            <EmptyAnswer pending={exec.isPending} />
          )}
        </div>
      </div>
    </div>
  );
}

function EmptyAnswer({ pending }: { pending: boolean }) {
  return (
    <Card className="flex min-h-[280px] flex-col items-center justify-center gap-3 p-10 text-center">
      <div className="grid h-11 w-11 place-items-center rounded-lg bg-muted">
        <Sparkles className="h-5 w-5 text-muted-foreground" />
      </div>
      <div className="text-sm font-medium">
        {pending ? 'Running retrieval pipeline…' : 'No answer yet'}
      </div>
      <p className="max-w-sm text-[13px] text-muted-foreground">
        Compose a question, pick at least one collection, and run the query to see the grounded
        answer, citations, the retrieval waterfall, and the 3-layer hallucination cascade.
      </p>
    </Card>
  );
}

// ---------- Answer ----------
function AnswerPanel({ result }: { result: QueryResponse }) {
  const grounding = result.grounding_score;
  const cascadeTone = verdictTone(result.judge_verdict ?? result.nli_verdict);
  const stats: { k: string; v: string; tone: Tone; sub: string }[] = [
    {
      k: 'Grounding',
      v: grounding !== null ? formatNumber(grounding, 2) : '—',
      tone: scoreTone(grounding),
      sub: '≥ 0.75 thresh',
    },
    {
      k: 'Latency',
      v: `${result.usage.latency_ms} ms`,
      tone: 'neutral',
      sub: 'wall clock',
    },
    {
      k: 'Tokens',
      v: `${result.usage.input_tokens} / ${result.usage.output_tokens}`,
      tone: 'neutral',
      sub: 'in / out',
    },
    {
      k: 'Cost',
      v: `$${formatNumber(result.usage.cost_usd, 5)}`,
      tone: 'neutral',
      sub: 'litellm metered',
    },
    {
      k: 'NLI · Judge',
      v: `${result.nli_verdict ?? 'off'} · ${result.judge_verdict ?? 'off'}`,
      tone: cascadeTone,
      sub: result.judge_verdict || result.nli_verdict ? 'cascade run' : 'not run',
    },
  ];

  return (
    <Card className="overflow-hidden">
      {/* stat strip */}
      <div className="grid grid-cols-2 divide-x divide-y divide-border border-b border-border sm:grid-cols-3 lg:grid-cols-5 lg:divide-y-0">
        {stats.map((s) => (
          <div key={s.k} className="p-3.5">
            <div className="text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
              {s.k}
            </div>
            <div
              className="mt-1 font-mono text-lg font-semibold"
              style={{ color: s.tone === 'neutral' ? undefined : `hsl(var(--${toneVar(s.tone)}))` }}
            >
              {s.v}
            </div>
            <div className="mt-0.5 text-[11px] text-muted-foreground">{s.sub}</div>
          </div>
        ))}
      </div>

      {/* answer body */}
      <div className="p-5">
        <div className="mb-3 flex items-center gap-2">
          <h2 className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
            answer
          </h2>
          <div className="flex-1" />
          <CopyButton label="copy" text={result.answer} icon={<Copy className="h-3 w-3" />} />
          <CopyButton
            label="permalink"
            text={result.query_session_id}
            icon={<Link2 className="h-3 w-3" />}
          />
        </div>
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
          {result.answer}
        </p>

        {result.citations.length > 0 && (
          <div className="mt-5">
            <SectionLabel className="mb-2">citations · {result.citations.length}</SectionLabel>
            <div className="flex flex-col gap-1.5">
              {result.citations.map((c) => (
                <CitationRow key={c.citation_id} c={c} />
              ))}
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}

function CitationRow({ c }: { c: CitationRead }) {
  const tone = scoreTone(c.relevance_score, 0.85);
  return (
    <div className="grid grid-cols-[24px_minmax(0,1fr)_auto] items-center gap-3 rounded-md border border-border bg-background p-2.5">
      <div className="grid h-[22px] w-[22px] place-items-center rounded-md bg-primary text-[11px] font-semibold text-primary-foreground">
        {c.citation_index}
      </div>
      <div className="min-w-0">
        <div className="truncate text-[13px] font-medium">
          doc <Mono>{c.document_id.slice(0, 8)}</Mono>
        </div>
        <div className="mt-0.5 truncate text-[11px] text-muted-foreground">
          {c.page_number !== null && `p${c.page_number}`}
          {c.section_title && ` · ${c.section_title}`}
          {c.quoted_text && ` · ${c.quoted_text}`}
        </div>
      </div>
      {c.relevance_score !== null && (
        <Badge variant={toneBadgeVariant[tone]} className="font-mono">
          {formatNumber(c.relevance_score, 3)}
        </Badge>
      )}
    </div>
  );
}

// ---------- small building blocks ----------
function Field({
  label,
  htmlFor,
  right,
  children,
}: {
  label: string;
  htmlFor?: string;
  right?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between">
        <Label htmlFor={htmlFor} className="text-xs font-medium">
          {label}
        </Label>
        {right}
      </div>
      {children}
    </div>
  );
}

function ToggleRow({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-xs">
      <span className="relative inline-flex h-3.5 w-[26px] items-center">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          className="absolute inset-0 z-10 m-0 cursor-pointer opacity-0"
        />
        <span
          className={cn(
            'h-3.5 w-[26px] rounded-full p-px transition-colors',
            checked ? 'bg-primary' : 'bg-border',
          )}
        >
          <span
            className={cn(
              'block h-3 w-3 rounded-full bg-background transition-transform',
              checked && 'translate-x-3',
            )}
          />
        </span>
      </span>
      <span className={checked ? 'text-foreground' : 'text-muted-foreground'}>{label}</span>
    </label>
  );
}

function CopyButton({
  label,
  text,
  icon,
}: {
  label: string;
  text: string;
  icon: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={() => navigator.clipboard?.writeText(text).catch(() => {})}
      className="inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
    >
      {icon} {label}
    </button>
  );
}

function toneVar(tone: Tone): string {
  switch (tone) {
    case 'success':
      return 'success-foreground';
    case 'warning':
      return 'warning-foreground';
    case 'danger':
      return 'danger-foreground';
    case 'info':
      return 'info-foreground';
    default:
      return 'foreground';
  }
}

function downloadJson(data: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
