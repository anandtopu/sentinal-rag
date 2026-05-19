'use client';

import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Pill } from '@/components/ui/pill';
import { Textarea } from '@/components/ui/textarea';
import type { QueryRequest, QueryResponse } from '@/lib/api-types';
import { useApiClient } from '@/lib/use-api-client';
import { formatNumber } from '@/lib/utils';

import { TraceViewer } from './trace-viewer';

export function QueryForm() {
  const { client } = useApiClient();
  const [query, setQuery] = useState('');
  const [collectionIds, setCollectionIds] = useState<string[]>([]);
  const [model, setModel] = useState('ollama/llama3.1:8b');
  const [topK, setTopK] = useState(8);
  const [showTrace, setShowTrace] = useState(true);
  const [result, setResult] = useState<QueryResponse | null>(null);

  const collections = useQuery({
    queryKey: ['collections'],
    queryFn: () => client.listCollections({ limit: 200 }),
  });

  const exec = useMutation({
    mutationFn: (payload: QueryRequest) => client.executeQuery(payload),
    onSuccess: (resp) => setResult(resp),
  });

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Ask</CardTitle>
          <CardDescription>
            Hybrid retrieval (BM25 + vector) → bge-reranker → Llama 3.1 8B via LiteLLM.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (!query.trim() || collectionIds.length === 0) return;
              exec.mutate({
                query,
                collection_ids: collectionIds,
                generation: { model },
                retrieval: { top_k_rerank: topK },
                options: { include_debug_trace: true },
              });
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="q">Question</Label>
              <Textarea
                id="q"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="What does the runbook say about pgvector index rebuilds?"
                rows={3}
              />
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <div className="space-y-2 md:col-span-2">
                <Label>Collections</Label>
                <div className="flex flex-wrap gap-2">
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
                  {!collections.data?.items.length && (
                    <span className="text-xs text-muted-foreground">
                      No collections — create one first.
                    </span>
                  )}
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="model">Model</Label>
                <Input id="model" value={model} onChange={(e) => setModel(e.target.value)} />
              </div>
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <div className="space-y-2">
                <Label htmlFor="topk">Top-k after rerank</Label>
                <Input
                  id="topk"
                  type="number"
                  min={1}
                  max={50}
                  value={topK}
                  onChange={(e) => setTopK(Number.parseInt(e.target.value, 10) || 8)}
                />
              </div>
              <div className="flex items-end">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={showTrace}
                    onChange={(e) => setShowTrace(e.target.checked)}
                  />
                  Show stage trace
                </label>
              </div>
              <div className="flex items-end justify-end">
                <Button
                  type="submit"
                  disabled={exec.isPending || !query.trim() || collectionIds.length === 0}
                >
                  {exec.isPending ? 'Running…' : 'Run query'}
                </Button>
              </div>
            </div>
            {exec.error && (
              <p className="text-sm text-destructive">{(exec.error as Error).message}</p>
            )}
          </form>
        </CardContent>
      </Card>

      {result && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>Answer</CardTitle>
              <div className="flex items-center gap-2 text-xs">
                <Badge variant="outline">latency {result.usage.latency_ms} ms</Badge>
                <Badge variant="outline">cost ${formatNumber(result.usage.cost_usd, 5)}</Badge>
                {result.grounding_score !== null && (
                  <Badge variant="success">
                    grounding {formatNumber(result.grounding_score, 3)}
                  </Badge>
                )}
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <p className="whitespace-pre-wrap text-sm leading-relaxed">{result.answer}</p>
            {result.citations.length > 0 && (
              <div className="mt-4 space-y-2">
                <div className="text-xs uppercase text-muted-foreground">Citations</div>
                <ol className="space-y-1 text-sm">
                  {result.citations.map((c) => (
                    <li key={c.citation_id} className="rounded border border-border px-3 py-2">
                      <div className="flex items-center justify-between text-xs text-muted-foreground">
                        <span>
                          [{c.citation_index}] doc {c.document_id.slice(0, 8)}
                          {c.page_number !== null && ` · p${c.page_number}`}
                          {c.section_title && ` · ${c.section_title}`}
                        </span>
                        {c.relevance_score !== null && (
                          <span>score {formatNumber(c.relevance_score, 3)}</span>
                        )}
                      </div>
                      {c.quoted_text && <div className="mt-1 text-sm">{c.quoted_text}</div>}
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {result && showTrace && <TraceViewer querySessionId={result.query_session_id} />}
    </div>
  );
}
