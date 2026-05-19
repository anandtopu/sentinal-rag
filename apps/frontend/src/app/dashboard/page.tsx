'use client';

import { useQuery } from '@tanstack/react-query';

import { PageHeader } from '@/components/layout/page-header';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Stat } from '@/components/ui/stat';
import { useApiClient } from '@/lib/use-api-client';

export default function DashboardPage() {
  const { client } = useApiClient();

  const tenant = useQuery({
    queryKey: ['me', 'tenant'],
    queryFn: () => client.myTenant(),
    retry: false,
  });
  const collections = useQuery({
    queryKey: ['collections'],
    queryFn: () => client.listCollections({ limit: 200 }),
    retry: false,
  });
  const evalRuns = useQuery({
    queryKey: ['eval-runs'],
    queryFn: () => client.listEvalRuns(),
  });

  const collectionCount = collections.data?.total ?? 0;
  const evalCount = evalRuns.data?.length ?? 0;
  const tenantName = tenant.data?.name ?? '—';
  const tenantSlug = tenant.data?.slug ?? '—';

  return (
    <div>
      <PageHeader
        title="Dashboard"
        description="Tenant overview, ingestion health, and recent evaluation runs."
      />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Stat
          label="Tenant"
          value={tenantName}
          sub={<code className="font-mono">{tenantSlug}</code>}
        />
        <Stat label="Collections" value={collectionCount} sub="Active scopes for retrieval" />
        <Stat label="Evaluation runs" value={evalCount} sub="Lifetime runs (ragas + custom)" />
      </div>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Architectural pillars</CardTitle>
          <CardDescription>The non-negotiables enforced across services.</CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="list-disc space-y-2 pl-5 text-sm text-muted-foreground">
            <li>RBAC injected at retrieval time, never post-mask.</li>
            <li>Tenant isolation via Postgres RLS as defense-in-depth.</li>
            <li>
              Every answer is fully traceable via <code>query_session_id</code>.
            </li>
            <li>
              Prompts are versioned artifacts; <code>prompt_version_id</code> is persisted.
            </li>
            <li>
              All LLM calls route through LiteLLM and double-entry into <code>usage_records</code>.
            </li>
            <li>Audit log is append-only and S3 Object-Lock mirrored.</li>
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
