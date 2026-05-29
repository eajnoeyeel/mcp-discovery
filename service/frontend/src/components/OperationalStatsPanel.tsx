import { Card, CardContent } from '@/components/ui/card';
import { cn } from '@/lib/utils';

interface OperationalStatsPanelProps {
  avgLatency?: number | null;
  p95Latency?: number | null;
  successRate?: number | null;
  callCount?: number;
}

interface StatCard {
  label: string;
  value: string;
  sub?: string;
  color: string;
}

function formatLatency(ms: number | null | undefined): string {
  if (ms == null) return '—';
  return `${Math.round(ms)}ms`;
}

function formatRate(rate: number | null | undefined): string {
  if (rate == null) return '—';
  return `${(rate * 100).toFixed(1)}%`;
}

function formatCount(count: number | undefined): string {
  if (count == null) return '—';
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
  if (count >= 1_000) return `${(count / 1_000).toFixed(1)}K`;
  return String(count);
}

function latencyColor(ms: number | null | undefined): string {
  if (ms == null) return 'text-muted-foreground';
  if (ms < 200) return 'text-success';
  if (ms < 500) return 'text-warning';
  return 'text-destructive';
}

function rateColor(rate: number | null | undefined): string {
  if (rate == null) return 'text-muted-foreground';
  if (rate >= 0.95) return 'text-success';
  if (rate >= 0.8) return 'text-warning';
  return 'text-destructive';
}

export default function OperationalStatsPanel({
  avgLatency,
  p95Latency,
  successRate,
  callCount,
}: OperationalStatsPanelProps) {
  const cards: StatCard[] = [
    {
      label: 'Avg Latency',
      value: formatLatency(avgLatency),
      color: latencyColor(avgLatency),
    },
    {
      label: 'P95 Latency',
      value: formatLatency(p95Latency),
      color: latencyColor(p95Latency),
    },
    {
      label: 'Success Rate',
      value: formatRate(successRate),
      color: rateColor(successRate),
    },
    {
      label: 'Total Calls',
      value: formatCount(callCount),
      color: 'text-foreground',
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {cards.map(({ label, value, color }) => (
        <Card key={label}>
          <CardContent className="p-4">
            <p className="text-xs text-muted-foreground">{label}</p>
            <p className={cn('mt-1 font-mono text-xl font-bold', color)}>{value}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
