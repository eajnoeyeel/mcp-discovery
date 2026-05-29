import { cn } from '@/lib/utils';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface SelectionRateChartProps {
  selectionRate?: number;
  selectionRate7d?: number;
  timesExposed?: number;
  timesSelected?: number;
}

function rateColor(rate: number | undefined): string {
  if (rate == null) return 'text-muted-foreground';
  if (rate >= 0.5) return 'text-success';
  if (rate >= 0.2) return 'text-warning';
  return 'text-destructive';
}

function trendIcon(current: number | undefined, prev: number | undefined): string | null {
  if (current == null || prev == null) return null;
  if (current > prev + 0.01) return '↑';
  if (current < prev - 0.01) return '↓';
  return '→';
}

function trendColor(current: number | undefined, prev: number | undefined): string {
  if (current == null || prev == null) return 'text-muted-foreground';
  if (current > prev + 0.01) return 'text-success';
  if (current < prev - 0.01) return 'text-destructive';
  return 'text-muted-foreground';
}

export default function SelectionRateChart({
  selectionRate,
  selectionRate7d,
  timesExposed,
  timesSelected,
}: SelectionRateChartProps) {
  const icon = trendIcon(selectionRate, selectionRate7d);
  const delta =
    selectionRate != null && selectionRate7d != null
      ? ((selectionRate - selectionRate7d) * 100).toFixed(1)
      : null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-semibold">Selection Rate</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-end gap-3">
          <span className={cn('font-mono text-4xl font-bold', rateColor(selectionRate))}>
            {selectionRate != null ? `${(selectionRate * 100).toFixed(1)}%` : '—'}
          </span>
          {icon != null && delta != null && (
            <div className={cn('flex items-center gap-0.5 mb-1 text-sm font-medium', trendColor(selectionRate, selectionRate7d))}>
              <span>{icon}</span>
              <span>{Math.abs(Number(delta))}pp vs 7d</span>
            </div>
          )}
        </div>

        {selectionRate != null && (
          <div className="mt-3 h-2 w-full rounded-full bg-secondary overflow-hidden">
            <div
              className={cn('h-full rounded-full transition-all', rateColor(selectionRate).replace('text-', 'bg-'))}
              style={{ width: `${Math.min(selectionRate * 100, 100)}%` }}
            />
          </div>
        )}

        <div className="mt-3 grid grid-cols-2 gap-3 border-t border-border pt-3">
          <div>
            <p className="text-xs text-muted-foreground">Exposures</p>
            <p className="font-mono text-sm font-medium text-foreground">
              {timesExposed != null ? timesExposed.toLocaleString() : '—'}
            </p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Selections</p>
            <p className="font-mono text-sm font-medium text-foreground">
              {timesSelected != null ? timesSelected.toLocaleString() : '—'}
            </p>
          </div>
          {selectionRate7d != null && (
            <div className="col-span-2">
              <p className="text-xs text-muted-foreground">7-day rate</p>
              <p className={cn('font-mono text-sm font-medium', rateColor(selectionRate7d))}>
                {(selectionRate7d * 100).toFixed(1)}%
              </p>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
