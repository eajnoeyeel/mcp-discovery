import { cn } from '@/lib/utils';
import { ArrowDownRight, ArrowUpRight } from 'lucide-react';

interface StatProps {
  label: string;
  value: string | number;
  unit?: string;
  delta?: {
    value: string;
    direction: 'up' | 'down' | 'flat';
    tone?: 'positive' | 'negative' | 'neutral';
  };
  className?: string;
}

/**
 * Stat primitive — uppercase label, large tabular-nums numeric value,
 * optional unit and delta pill. Use inside StatGrid.
 */
export default function Stat({ label, value, unit, delta, className }: StatProps) {
  const deltaTone =
    delta?.tone === 'positive'
      ? 'bg-success/10 text-success'
      : delta?.tone === 'negative'
        ? 'bg-destructive/10 text-destructive'
        : 'bg-muted text-muted-foreground';

  const DeltaIcon =
    delta?.direction === 'up'
      ? ArrowUpRight
      : delta?.direction === 'down'
        ? ArrowDownRight
        : null;

  return (
    <div
      className={cn(
        'rounded-[14px] bg-card p-6 ring-1 ring-border/60 transition-shadow hover:ring-primary/40',
        className,
      )}
    >
      <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </p>
      <div className="mt-3 flex items-baseline gap-2">
        <span className="font-semibold text-[44px] leading-none tracking-[-0.04em] tabular-nums text-foreground">
          {value}
        </span>
        {unit && (
          <span className="text-sm font-medium text-muted-foreground">{unit}</span>
        )}
      </div>
      {delta && (
        <div className="mt-3">
          <span
            className={cn(
              'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium',
              deltaTone,
            )}
          >
            {DeltaIcon && <DeltaIcon className="h-3 w-3" />}
            {delta.value}
          </span>
        </div>
      )}
    </div>
  );
}
