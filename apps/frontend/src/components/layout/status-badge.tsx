import { Badge, type BadgeProps } from '@/components/ui/badge';

const VARIANT: Record<string, BadgeProps['variant']> = {
  ready: 'success',
  active: 'success',
  completed: 'success',
  succeeded: 'success',
  pending: 'warning',
  queued: 'warning',
  invited: 'warning',
  processing: 'warning',
  running: 'warning',
  failed: 'destructive',
  disabled: 'destructive',
  suspended: 'destructive',
};

export function StatusBadge({ status }: { status: string }) {
  const variant: BadgeProps['variant'] = VARIANT[status?.toLowerCase()] ?? 'outline';
  return (
    <Badge variant={variant} dot={variant !== 'outline'}>
      {status}
    </Badge>
  );
}
