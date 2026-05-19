import { type ButtonHTMLAttributes, forwardRef } from 'react';

import { cn } from '@/lib/utils';

export interface PillProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  pressed?: boolean;
}

export const Pill = forwardRef<HTMLButtonElement, PillProps>(
  ({ className, pressed, type = 'button', ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      aria-pressed={pressed}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background disabled:pointer-events-none disabled:opacity-50',
        pressed
          ? 'border-primary bg-primary text-primary-foreground'
          : 'border-border bg-background text-foreground hover:bg-muted',
        className,
      )}
      {...props}
    />
  ),
);
Pill.displayName = 'Pill';
