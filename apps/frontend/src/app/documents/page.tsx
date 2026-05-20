'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ChevronDown,
  Eye,
  Filter,
  Folder,
  MoreHorizontal,
  RefreshCw,
  Search,
  Upload,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';

import { PageHeader } from '@/components/layout/page-header';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Mono } from '@/components/ui/mono';
import { SectionLabel } from '@/components/ui/section-label';
import type { DocumentRow, IngestionJob } from '@/lib/api-types';
import { type Tone, statusTone, toneBadgeVariant, toneColor } from '@/lib/tone';
import { useApiClient } from '@/lib/use-api-client';
import { cn, formatDateTime } from '@/lib/utils';

const WORKFLOW_STAGES = ['parse', 'chunk', 'embed', 'upsert', 'verify'];

export default function DocumentsPage() {
  const { client } = useApiClient();
  const qc = useQueryClient();
  const [collectionId, setCollectionId] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const [filter, setFilter] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadOk, setUploadOk] = useState<string | null>(null);

  const collections = useQuery({
    queryKey: ['collections'],
    queryFn: () => client.listCollections({ limit: 200 }),
  });

  useEffect(() => {
    if (!collectionId && collections.data?.items.length) {
      setCollectionId(collections.data.items[0].id);
    }
  }, [collectionId, collections.data]);

  const docs = useQuery({
    queryKey: ['documents', collectionId],
    queryFn: () => client.listDocuments(collectionId),
    enabled: Boolean(collectionId),
  });
  const jobs = useQuery({
    queryKey: ['ingestion-jobs', collectionId],
    queryFn: () => client.listIngestionJobs(collectionId),
    enabled: Boolean(collectionId),
    refetchInterval: 5_000,
  });

  const upload = useMutation({
    mutationFn: (file: File) =>
      client.uploadDocument({ collection_id: collectionId, file, title: file.name }),
    onSuccess: (resp) => {
      setUploadOk(`Queued ingestion job ${resp.ingestion_job_id.slice(0, 8)}…`);
      setUploadError(null);
      void qc.invalidateQueries({ queryKey: ['documents', collectionId] });
      void qc.invalidateQueries({ queryKey: ['ingestion-jobs', collectionId] });
      if (fileInputRef.current) fileInputRef.current.value = '';
    },
    onError: (err: Error) => {
      setUploadError(err.message);
      setUploadOk(null);
    },
  });

  const items = docs.data?.items ?? [];
  const filtered = useMemo(
    () =>
      filter.trim()
        ? items.filter((d) => d.title.toLowerCase().includes(filter.trim().toLowerCase()))
        : items,
    [items, filter],
  );
  const selected = filtered.find((d) => d.id === selectedId) ?? filtered[0] ?? null;

  return (
    <div>
      <PageHeader
        title="Documents"
        description="Inspect documents and their ingestion lineage. Workflows run on Temporal."
        actions={
          <>
            <div className="relative">
              <Folder className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
              <select
                aria-label="Collection"
                value={collectionId}
                onChange={(e) => {
                  setCollectionId(e.target.value);
                  setSelectedId('');
                }}
                className="h-8 appearance-none rounded-md border border-border bg-background pl-8 pr-7 font-mono text-[12px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {collections.data?.items.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
                {!collections.data?.items.length && <option value="">No collections</option>}
              </select>
            </div>
            <Button variant="outline" size="sm">
              <Filter className="h-3.5 w-3.5" /> Filters
            </Button>
            <label
              className={cn(
                'inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-md bg-primary px-3 text-[13px] font-medium text-primary-foreground transition-colors hover:bg-primary/90',
                (!collectionId || upload.isPending) && 'pointer-events-none opacity-50',
              )}
            >
              <Upload className="h-3.5 w-3.5" />
              {upload.isPending ? 'Uploading…' : 'Upload'}
              <input
                ref={fileInputRef}
                id="file"
                type="file"
                aria-label="File"
                accept=".pdf,.txt,.md,.html,.docx"
                disabled={!collectionId || upload.isPending}
                className="sr-only"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) upload.mutate(file);
                }}
              />
            </label>
          </>
        }
      />

      {(uploadOk || uploadError) && (
        <div className="mb-3 text-sm">
          {uploadOk && <span className="text-success-foreground">{uploadOk}</span>}
          {uploadError && <span className="text-destructive">{uploadError}</span>}
        </div>
      )}

      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[1.05fr_1.6fr]">
        {/* list */}
        <Card className="overflow-hidden">
          <div className="flex items-center gap-2 border-b border-border p-3">
            <div className="flex h-7 flex-1 items-center gap-1.5 rounded-md bg-muted px-2.5 text-xs text-muted-foreground">
              <Search className="h-3.5 w-3.5" />
              <input
                aria-label="Filter documents"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder={`Filter ${items.length} documents…`}
                className="w-full bg-transparent outline-none placeholder:text-muted-foreground"
              />
            </div>
          </div>
          <div className="flex items-center gap-2 border-b border-border px-3 py-2">
            <Mono dim>{items.length} docs in collection</Mono>
          </div>
          {filtered.map((d) => (
            <DocRow
              key={d.id}
              d={d}
              selected={selected?.id === d.id}
              onSelect={() => setSelectedId(d.id)}
            />
          ))}
          {!filtered.length && (
            <div className="px-4 py-8 text-center text-[13px] text-muted-foreground">
              {docs.isLoading ? 'Loading…' : 'No documents in this collection.'}
            </div>
          )}
        </Card>

        {/* detail */}
        {selected ? (
          <DocumentDetail doc={selected} jobs={jobs.data ?? []} />
        ) : (
          <Card className="flex min-h-[280px] items-center justify-center p-10 text-center text-[13px] text-muted-foreground">
            Select a document to inspect its ingestion lineage.
          </Card>
        )}
      </div>
    </div>
  );
}

function fileType(d: DocumentRow): string {
  const ext = d.title.split('.').pop()?.toLowerCase();
  if (ext && ext.length <= 4 && ext !== d.title.toLowerCase()) return ext;
  if (d.mime_type?.includes('pdf')) return 'pdf';
  if (d.mime_type?.includes('word')) return 'docx';
  if (d.mime_type?.includes('html')) return 'html';
  return 'txt';
}

function FileGlyph({ type }: { type: string }) {
  const color: Record<string, string> = {
    pdf: 'text-danger-foreground',
    docx: 'text-info-foreground',
    html: 'text-warning-foreground',
  };
  return (
    <div
      className={cn(
        'grid h-[22px] w-[22px] shrink-0 place-items-center rounded bg-muted font-mono text-[9px] font-semibold tracking-wide',
        color[type] ?? 'text-muted-foreground',
      )}
    >
      {type.toUpperCase()}
    </div>
  );
}

function sensitivityTone(s: string): Tone {
  if (s === 'confidential') return 'warning';
  if (s === 'restricted') return 'danger';
  return 'neutral';
}

function DocRow({
  d,
  selected,
  onSelect,
}: {
  d: DocumentRow;
  selected: boolean;
  onSelect: () => void;
}) {
  const tone = statusTone(d.status);
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        'grid w-full grid-cols-[24px_minmax(0,1fr)_auto] items-center gap-2.5 border-b border-l-2 border-border px-3.5 py-2.5 text-left transition-colors',
        selected ? 'border-l-primary bg-muted' : 'border-l-transparent hover:bg-muted/50',
      )}
    >
      <FileGlyph type={fileType(d)} />
      <div className="min-w-0">
        <div className="truncate text-[13px] font-medium">{d.title}</div>
        <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
          <Mono dim>{d.id.slice(0, 8)}</Mono>
          <span>·</span>
          <span>{formatDateTime(d.updated_at)}</span>
          <Badge
            variant={toneBadgeVariant[sensitivityTone(d.sensitivity_level)]}
            className="px-1.5 py-0 font-mono text-[10px]"
          >
            {d.sensitivity_level}
          </Badge>
        </div>
      </div>
      <Badge variant={toneBadgeVariant[tone]} dot pulse={d.status === 'processing'}>
        {d.status}
      </Badge>
    </button>
  );
}

function DocumentDetail({ doc, jobs }: { doc: DocumentRow; jobs: IngestionJob[] }) {
  const meta: { k: string; v: React.ReactNode }[] = [
    {
      k: 'Status',
      v: (
        <Badge variant={toneBadgeVariant[statusTone(doc.status)]} dot>
          {doc.status}
        </Badge>
      ),
    },
    { k: 'Sensitivity', v: <Mono>{doc.sensitivity_level}</Mono> },
    { k: 'Type', v: <Mono>{fileType(doc)}</Mono> },
    { k: 'Created', v: <Mono>{formatDateTime(doc.created_at)}</Mono> },
    { k: 'Updated', v: <Mono>{formatDateTime(doc.updated_at)}</Mono> },
  ];

  return (
    <div className="flex flex-col gap-4">
      {/* header */}
      <Card className="p-4">
        <div className="flex items-start gap-3">
          <FileGlyph type={fileType(doc)} />
          <div className="min-w-0 flex-1">
            <div className="text-[17px] font-semibold tracking-tight">{doc.title}</div>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <Mono dim>{doc.id}</Mono>
              {doc.source_uri && (
                <>
                  <span className="text-[11px] text-muted-foreground">·</span>
                  <Mono dim>{doc.source_uri}</Mono>
                </>
              )}
            </div>
          </div>
          <div className="flex gap-1.5">
            <Button variant="outline" size="sm">
              <Eye className="h-3.5 w-3.5" /> Preview
            </Button>
            <Button variant="outline" size="sm">
              <RefreshCw className="h-3.5 w-3.5" /> Reindex
            </Button>
            <Button variant="outline" size="icon" className="h-8 w-8" aria-label="More">
              <MoreHorizontal className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-3 border-t border-border pt-3.5 sm:grid-cols-5">
          {meta.map((m) => (
            <div key={m.k}>
              <div className="text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
                {m.k}
              </div>
              <div className="mt-1">{m.v}</div>
            </div>
          ))}
        </div>
      </Card>

      {/* ingestion lineage */}
      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-4 py-3.5">
          <div>
            <div className="text-sm font-semibold tracking-tight">Ingestion lineage</div>
            <div className="mt-0.5 text-xs text-muted-foreground">
              Temporal workflow runs for this collection. Newest first.
            </div>
          </div>
        </div>
        <div className="p-4">
          {jobs.length === 0 && (
            <div className="py-3 text-center text-[13px] text-muted-foreground">
              No ingestion runs recorded yet.
            </div>
          )}
          {jobs.slice(0, 5).map((j, i) => (
            <LineageRow key={j.id} job={j} first={i === 0} />
          ))}
        </div>
      </Card>

      {/* chunks preview — needs a chunks endpoint, not yet wired */}
      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-4 py-3.5">
          <div className="text-sm font-semibold tracking-tight">Chunks · preview</div>
        </div>
        <div className="px-4 py-8 text-center text-[13px] text-muted-foreground">
          Chunk-level preview needs a chunks endpoint. Vector &amp; BM25 indexing status shows in
          the lineage above.
        </div>
      </Card>
    </div>
  );
}

function LineageRow({ job, first }: { job: IngestionJob; first: boolean }) {
  const tone = statusTone(job.status);
  const durationS =
    job.started_at && job.completed_at
      ? (new Date(job.completed_at).getTime() - new Date(job.started_at).getTime()) / 1000
      : null;
  return (
    <div
      className={cn(
        'grid grid-cols-[88px_minmax(0,1fr)_auto] items-center gap-3 py-2.5',
        first ? '' : 'border-t border-dashed border-border',
      )}
    >
      <Mono dim>{job.id.slice(0, 8)}</Mono>
      <div className="flex flex-wrap items-center gap-y-1">
        {/* The workflow stage chain is the pipeline definition; per-stage status
            isn't captured, so the chain is tinted by the run's overall status. */}
        {WORKFLOW_STAGES.map((stage, i) => (
          <div key={stage} className="flex items-center">
            <span
              className="h-2 w-2 rounded-sm"
              style={{ background: toneColor[tone] }}
              aria-hidden
            />
            <span className="ml-1.5 text-[11px]">{stage}</span>
            {i < WORKFLOW_STAGES.length - 1 && <span className="mx-1.5 h-px w-4 bg-border" />}
          </div>
        ))}
      </div>
      <div className="flex items-center gap-2">
        {durationS !== null && <Mono dim>{durationS.toFixed(1)}s</Mono>}
        <Badge variant={toneBadgeVariant[tone]} dot pulse={job.status === 'processing'}>
          {job.status}
        </Badge>
      </div>
    </div>
  );
}
