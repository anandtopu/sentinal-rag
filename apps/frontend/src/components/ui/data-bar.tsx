import { cn } from '@/lib/utils';

/** Horizontal data bar for progress and distribution rows. */
export function DataBar({
  value,
  max = 1,
  color = 'hsl(var(--primary))',
  track = 'hsl(var(--muted))',
  height = 6,
  className,
}: {
  value: number;
  max?: number;
  color?: string;
  track?: string;
  height?: number;
  className?: string;
}) {
  const pct = Math.max(0, Math.min(1, max === 0 ? 0 : value / max));
  return (
    <div
      className={cn('w-full overflow-hidden rounded-full', className)}
      style={{ height, background: track }}
    >
      <div style={{ width: `${pct * 100}%`, height: '100%', background: color }} />
    </div>
  );
}
