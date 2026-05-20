import type { ReactNode } from 'react';

import { type Tone, toneColor } from '@/lib/tone';

/**
 * Bordered topbar chip pairing a mono label with a tone-colored value
 * (p95, error rate, MTD cost…). Pass `value="—"` for an honest empty slot
 * when the metric has no backing data yet.
 */
export function SignalChip({
  label,
  value,
  tone = 'neutral',
  title,
}: {
  label: string;
  value: ReactNode;
  tone?: Tone;
  title?: string;
}) {
  return (
    <div
      title={title}
      className="inline-flex items-baseline gap-1.5 whitespace-nowrap rounded-md border border-border bg-background px-2.5 py-1"
    >
      <span className="font-mono text-[10px] uppercase tracking-[0.06em] text-muted-foreground">
        {label}
      </span>
      <span className="font-mono text-xs font-medium" style={{ color: toneColor[tone] }}>
        {value}
      </span>
    </div>
  );
}
