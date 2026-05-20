import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

/** Small mono uppercase label that anchors a panel section. */
export function SectionLabel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground',
        className,
      )}
    >
      {children}
    </div>
  );
}
