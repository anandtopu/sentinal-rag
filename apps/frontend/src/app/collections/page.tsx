'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Filter, Folder, Layers, MoreHorizontal, Plus } from 'lucide-react';
import { useMemo, useState } from 'react';

import { PageHeader } from '@/components/layout/page-header';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Mono } from '@/components/ui/mono';
import { Textarea } from '@/components/ui/textarea';
import type { Collection, CollectionCreate } from '@/lib/api-types';
import { type Tone, toneBadgeVariant } from '@/lib/tone';
import { useApiClient } from '@/lib/use-api-client';
import { cn, formatDateTime } from '@/lib/utils';

type VisFilter = 'all' | 'private' | 'tenant' | 'public';

function visTone(v: string): Tone {
  if (v === 'public') return 'info';
  if (v === 'private') return 'warning';
  return 'neutral';
}

export default function CollectionsPage() {
  const { client } = useApiClient();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [vis, setVis] = useState<VisFilter>('all');
  const [form, setForm] = useState<CollectionCreate>({
    name: '',
    description: '',
    visibility: 'tenant',
  });
  const [error, setError] = useState<string | null>(null);

  const collections = useQuery({
    queryKey: ['collections'],
    queryFn: () => client.listCollections({ limit: 200 }),
  });

  const createMutation = useMutation({
    mutationFn: (payload: CollectionCreate) => client.createCollection(payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['collections'] });
      setOpen(false);
      setForm({ name: '', description: '', visibility: 'tenant' });
      setError(null);
    },
    onError: (err: Error) => setError(err.message),
  });

  const items = collections.data?.items ?? [];
  const counts = useMemo(() => {
    const c = { all: items.length, private: 0, tenant: 0, public: 0 };
    for (const it of items) c[it.visibility] += 1;
    return c;
  }, [items]);
  const filtered = vis === 'all' ? items : items.filter((c) => c.visibility === vis);

  return (
    <div>
      <PageHeader
        title="Collections"
        description="Logical scopes for ingestion + retrieval. RBAC is enforced per-collection."
        actions={
          <>
            <Button variant="outline" size="sm">
              <Filter className="h-3.5 w-3.5" /> Filters
            </Button>
            <Button variant="outline" size="sm">
              <Layers className="h-3.5 w-3.5" /> Group
            </Button>
            <Button size="sm" onClick={() => setOpen((v) => !v)}>
              {open ? 'Cancel' : 'New collection'}
            </Button>
          </>
        }
      />

      {/* counters / visibility filter */}
      <div className="mb-3.5 flex flex-wrap items-center gap-1.5">
        <FilterTab
          on={vis === 'all'}
          count={counts.all}
          label="All"
          onClick={() => setVis('all')}
        />
        <FilterTab
          on={vis === 'private'}
          count={counts.private}
          label="private"
          onClick={() => setVis('private')}
        />
        <FilterTab
          on={vis === 'tenant'}
          count={counts.tenant}
          label="tenant"
          onClick={() => setVis('tenant')}
        />
        <FilterTab
          on={vis === 'public'}
          count={counts.public}
          label="public"
          onClick={() => setVis('public')}
        />
      </div>

      {open && (
        <Card className="mb-4 p-4">
          <form
            className="grid gap-4 md:grid-cols-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (!form.name) {
                setError('Name required.');
                return;
              }
              createMutation.mutate(form);
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="name">Name</Label>
              <Input
                id="name"
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="visibility">Visibility</Label>
              <select
                id="visibility"
                className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm shadow-sm"
                value={form.visibility}
                onChange={(e) =>
                  setForm({ ...form, visibility: e.target.value as CollectionCreate['visibility'] })
                }
              >
                <option value="private">private</option>
                <option value="tenant">tenant</option>
                <option value="public">public</option>
              </select>
            </div>
            <div className="space-y-2 md:col-span-2">
              <Label htmlFor="description">Description</Label>
              <Textarea
                id="description"
                value={form.description ?? ''}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </div>
            {error && <div className="text-sm text-destructive md:col-span-2">{error}</div>}
            <div className="md:col-span-2">
              <Button type="submit" disabled={createMutation.isPending}>
                {createMutation.isPending ? 'Creating…' : 'Create collection'}
              </Button>
            </div>
          </form>
        </Card>
      )}

      {collections.isLoading && (
        <div className="text-sm text-muted-foreground">Loading collections…</div>
      )}
      {collections.error && (
        <div className="text-sm text-destructive">{(collections.error as Error).message}</div>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {filtered.map((c) => (
          <CollectionCard key={c.id} c={c} />
        ))}

        {/* new-collection tile */}
        <button
          type="button"
          aria-label="Add collection"
          onClick={() => setOpen(true)}
          className="flex min-h-[150px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
        >
          <Plus className="h-5 w-5" />
          <div className="text-[13px]">New collection</div>
          <div className="text-[11px]">tenant · private · public</div>
        </button>
      </div>

      {collections.data && items.length === 0 && (
        <div className="mt-3 text-sm text-muted-foreground">
          No collections yet — create your first scope.
        </div>
      )}
    </div>
  );
}

function FilterTab({
  on,
  count,
  label,
  onClick,
}: {
  on: boolean;
  count: number;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors',
        on
          ? 'border-primary bg-primary text-primary-foreground'
          : 'border-border bg-background text-foreground hover:bg-muted',
      )}
    >
      <span className={cn('font-mono text-[11px]', on ? 'opacity-80' : 'opacity-60')}>{count}</span>
      {label}
    </button>
  );
}

function CollectionCard({ c }: { c: Collection }) {
  return (
    <Card className="flex flex-col">
      <div className="p-4">
        <div className="mb-1.5 flex items-center gap-2">
          <Folder className="h-4 w-4 shrink-0" />
          <div className="min-w-0 flex-1 truncate text-[15px] font-semibold tracking-tight">
            {c.name}
          </div>
          <MoreHorizontal className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        </div>
        <p className="min-h-[34px] text-xs leading-[17px] text-muted-foreground">
          {c.description ?? 'No description.'}
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <Badge variant={toneBadgeVariant[visTone(c.visibility)]} dot>
            {c.visibility}
          </Badge>
        </div>
      </div>
      <div className="mt-auto flex items-center gap-2 border-t border-border px-4 py-2.5">
        <Mono dim>created {formatDateTime(c.created_at)}</Mono>
      </div>
    </Card>
  );
}
