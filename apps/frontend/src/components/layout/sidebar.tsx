'use client';

import { useQuery } from '@tanstack/react-query';
import {
  BarChart3,
  ChevronDown,
  Database,
  FileSearch,
  FileText,
  Folder,
  Gauge,
  GitBranch,
  type LucideIcon,
  ScrollText,
  Settings,
  Sparkles,
} from 'lucide-react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { Badge } from '@/components/ui/badge';
import { Mono } from '@/components/ui/mono';
import { useApiClient } from '@/lib/use-api-client';
import { cn } from '@/lib/utils';

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Resolved live count, when one is available for this section. */
  count?: number;
  badge?: string;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const APP_VERSION = process.env.NEXT_PUBLIC_APP_VERSION ?? 'v0.6';
const BUILD_SHA = process.env.NEXT_PUBLIC_BUILD_SHA;

export function Sidebar() {
  const pathname = usePathname();
  const { client } = useApiClient();

  // The only count the API can resolve cheaply is the collection total; other
  // sections stay count-less rather than show a fabricated number.
  const collections = useQuery({
    queryKey: ['collections'],
    queryFn: () => client.listCollections({ limit: 200 }),
    retry: false,
  });
  const tenant = useQuery({
    queryKey: ['me', 'tenant'],
    queryFn: () => client.myTenant(),
    retry: false,
  });

  const groups: NavGroup[] = [
    {
      label: 'Operate',
      items: [
        { href: '/dashboard', label: 'Dashboard', icon: Gauge },
        { href: '/query-playground', label: 'Query Playground', icon: Sparkles, badge: 'live' },
      ],
    },
    {
      label: 'Knowledge',
      items: [
        {
          href: '/collections',
          label: 'Collections',
          icon: Folder,
          count: collections.data?.total,
        },
        { href: '/documents', label: 'Documents', icon: FileText },
      ],
    },
    {
      label: 'Quality',
      items: [
        { href: '/evaluations', label: 'Evaluations', icon: BarChart3 },
        { href: '/prompts', label: 'Prompts', icon: ScrollText },
      ],
    },
    {
      label: 'Observe',
      items: [
        { href: '/audit', label: 'Audit', icon: FileSearch },
        { href: '/usage', label: 'Usage', icon: Database },
        { href: '/settings', label: 'Settings', icon: Settings },
      ],
    },
  ];

  const tenantLine = tenant.data ? `${tenant.data.slug} · ${tenant.data.plan}` : 'Enterprise RAG';

  return (
    <aside className="hidden w-60 shrink-0 flex-col border-r border-border bg-background md:flex">
      {/* brand */}
      <div className="flex h-14 items-center gap-2.5 border-b border-border px-4">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
          <span className="text-xs font-bold tracking-tight">SR</span>
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold leading-none">SentinelRAG</div>
          <div className="mt-1 truncate text-[11px] text-muted-foreground">{tenantLine}</div>
        </div>
        <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
      </div>

      {/* grouped nav */}
      <nav className="flex-1 overflow-y-auto p-2 text-[13px]">
        {groups.map((group) => (
          <div key={group.label} className="mb-3.5">
            <div className="px-3 pb-1.5 pt-1 font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              {group.label}
            </div>
            {group.items.map((item) => {
              const Icon = item.icon;
              const active = pathname?.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    'mb-0.5 flex items-center gap-2.5 rounded-md px-3 py-1.5 transition-colors',
                    active
                      ? 'bg-muted font-medium text-foreground'
                      : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground',
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" strokeWidth={1.75} />
                  <span className="flex-1 truncate">{item.label}</span>
                  {item.count !== undefined && (
                    <Mono dim className="text-[11px]">
                      {item.count.toLocaleString()}
                    </Mono>
                  )}
                  {item.badge && (
                    <Badge variant="info" dot pulse className="px-1.5 py-0 text-[10px]">
                      {item.badge}
                    </Badge>
                  )}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      {/* build footer */}
      <div className="flex items-center gap-2 border-t border-border px-3 py-2.5 text-[11px] text-muted-foreground">
        <GitBranch className="h-3 w-3" />
        <Mono dim className="text-[11px]">
          main{BUILD_SHA ? ` · ${BUILD_SHA.slice(0, 7)}` : ''}
        </Mono>
        <span className="ml-auto">{APP_VERSION}</span>
      </div>
    </aside>
  );
}
