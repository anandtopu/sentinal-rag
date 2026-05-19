import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

interface StatProps {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  className?: string;
}

export function Stat({ label, value, sub, className }: StatProps) {
  return (
    <div className={cn('rounded-md border border-border bg-background p-4 shadow-sm', className)}>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-[22px] font-semibold leading-7 tracking-tight">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted-foreground">{sub}</div>}
    </div>
  );
}
