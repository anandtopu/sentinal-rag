import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

/** Monospace inline text for IDs, models, scores — the identifying data. */
export function Mono({
  children,
  dim,
  className,
}: {
  children: ReactNode;
  dim?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cn(
        'font-mono text-xs tracking-normal',
        dim ? 'text-muted-foreground' : 'text-foreground',
        className,
      )}
    >
      {children}
    </span>
  );
}

/** Keyboard-key affordance (⌘K, ⌘↵, /). */
export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd
      className={cn(
        'inline-flex items-center rounded border border-border bg-background px-1.5 py-px font-mono text-[11px] leading-[14px] text-muted-foreground',
        'shadow-[inset_0_-1px_0_hsl(var(--border))]',
        className,
      )}
    >
      {children}
    </kbd>
  );
}
