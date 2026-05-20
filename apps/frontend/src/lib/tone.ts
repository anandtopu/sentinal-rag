/**
 * Operator-signal tones shared across the redesigned console.
 *
 * One vocabulary (success / warning / danger / info / neutral) maps to both a
 * foreground color (text, sparkline strokes, status dots) and the matching
 * `Badge` variant, so a status computed once renders consistently whether it
 * lands in a pill, a chip, a bar, or a chart.
 */

import type { BadgeProps } from '@/components/ui/badge';

export type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral';

/** CSS color for text / SVG strokes / `bg-current` dots. */
export const toneColor: Record<Tone, string> = {
  success: 'hsl(var(--success-foreground))',
  warning: 'hsl(var(--warning-foreground))',
  danger: 'hsl(var(--danger-foreground))',
  info: 'hsl(var(--info-foreground))',
  neutral: 'hsl(var(--foreground))',
};

/** Matching `Badge` variant for a tone. */
export const toneBadgeVariant: Record<Tone, NonNullable<BadgeProps['variant']>> = {
  success: 'success',
  warning: 'warning',
  danger: 'destructive',
  info: 'info',
  neutral: 'secondary',
};

/**
 * Map a backend status string to a tone. Covers ingestion / document / job /
 * eval-run lifecycles. Unknown statuses fall back to neutral.
 */
export function statusTone(status: string | null | undefined): Tone {
  switch ((status ?? '').toLowerCase()) {
    case 'ready':
    case 'indexed':
    case 'active':
    case 'completed':
    case 'succeeded':
    case 'success':
      return 'success';
    case 'processing':
    case 'running':
      return 'info';
    case 'pending':
    case 'queued':
    case 'invited':
      return 'warning';
    case 'failed':
    case 'error':
    case 'disabled':
    case 'suspended':
      return 'danger';
    default:
      return 'neutral';
  }
}

/** Tone for a token-overlap / grounding score against a 0.75 threshold. */
export function scoreTone(score: number | null | undefined, threshold = 0.75): Tone {
  if (score === null || score === undefined || Number.isNaN(score)) return 'neutral';
  if (score >= threshold) return 'success';
  if (score >= threshold * 0.6) return 'info';
  return 'warning';
}

/** Tone for an NLI / LLM-judge verdict. */
export function verdictTone(verdict: string | null | undefined): Tone {
  switch ((verdict ?? '').toLowerCase()) {
    case 'entail':
    case 'pass':
    case 'grounded':
      return 'success';
    case 'neutral':
    case 'skipped':
      return 'warning';
    case 'contradict':
    case 'fail':
      return 'danger';
    default:
      return 'neutral';
  }
}
