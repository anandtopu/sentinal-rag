'use client';

import {
  BarChart3,
  Database,
  FileSearch,
  FileText,
  Folder,
  Gauge,
  type LucideIcon,
  ScrollText,
  Settings,
  Sparkles,
} from 'lucide-react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { cn } from '@/lib/utils';

const NAV: { href: string; label: string; icon: LucideIcon }[] = [
  { href: '/dashboard', label: 'Dashboard', icon: Gauge },
  { href: '/collections', label: 'Collections', icon: Folder },
  { href: '/documents', label: 'Documents', icon: FileText },
  { href: '/query-playground', label: 'Query Playground', icon: Sparkles },
  { href: '/evaluations', label: 'Evaluations', icon: BarChart3 },
  { href: '/prompts', label: 'Prompts', icon: ScrollText },
  { href: '/audit', label: 'Audit', icon: FileSearch },
  { href: '/usage', label: 'Usage', icon: Database },
  { href: '/settings', label: 'Settings', icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="hidden w-60 shrink-0 border-r border-border bg-background md:flex md:flex-col">
      <div className="flex h-14 items-center gap-2 border-b border-border px-4">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
          <span className="text-xs font-bold">SR</span>
        </div>
        <div className="flex flex-col">
          <span className="text-sm font-semibold leading-none">SentinelRAG</span>
          <span className="text-xs text-muted-foreground">Enterprise RAG</span>
        </div>
      </div>
      <nav className="flex-1 overflow-y-auto p-2 text-sm">
        {NAV.map((item) => {
          const Icon = item.icon;
          const active = pathname?.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                'flex items-center gap-2 rounded-md px-3 py-2 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground',
                active && 'bg-accent text-accent-foreground',
              )}
            >
              <Icon className="h-4 w-4" strokeWidth={1.75} />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-border p-3 text-xs text-muted-foreground">
        Phase 5 — UI in progress
      </div>
    </aside>
  );
}
