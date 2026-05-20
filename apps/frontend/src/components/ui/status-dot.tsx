import { cn } from '@/lib/utils';

/**
 * Status dot that inherits its color from the current text color (`bg-current`)
 * so it tints to whatever tone wraps it. `pulse` adds an expanding ring for
 * live / processing state.
 */
export function StatusDot({ className, pulse }: { className?: string; pulse?: boolean }) {
  return (
    <span className={cn('relative inline-flex h-2 w-2 shrink-0', className)} aria-hidden>
      <span className="absolute inset-0 rounded-full bg-current" />
      {pulse && (
        <span className="absolute -inset-0.5 rounded-full bg-current opacity-30 animate-sr-ping" />
      )}
    </span>
  );
}
