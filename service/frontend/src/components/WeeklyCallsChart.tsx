import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface DailyStat {
  day: string;
  call_count: number;
  client_id: string;
}

interface WeeklyCallsChartProps {
  data: DailyStat[];
}

interface AggregatedDay {
  day: string;
  label: string;
  total: number;
}

function aggregateByDay(data: DailyStat[]): AggregatedDay[] {
  const map = new Map<string, number>();
  for (const entry of data) {
    map.set(entry.day, (map.get(entry.day) ?? 0) + entry.call_count);
  }

  const sorted = Array.from(map.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .slice(-30);

  return sorted.map(([day, total]) => {
    const date = new Date(day);
    const label = `${date.getMonth() + 1}/${date.getDate()}`;
    return { day, label, total };
  });
}

export default function WeeklyCallsChart({ data }: WeeklyCallsChartProps) {
  const aggregated = aggregateByDay(data);
  const maxTotal = Math.max(...aggregated.map(d => d.total), 1);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-semibold">Daily Calls (Last 30 Days)</CardTitle>
      </CardHeader>
      <CardContent>
        {aggregated.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">No data available</p>
        ) : (
          <div className="flex items-end gap-0.5 h-32 overflow-x-auto pb-5 relative">
            {aggregated.map(({ day, label, total }) => {
              const heightPct = (total / maxTotal) * 100;
              const showLabel = aggregated.length <= 15 || aggregated.indexOf({ day, label, total }) % 5 === 0;
              return (
                <div
                  key={day}
                  className="group relative flex flex-1 min-w-[6px] flex-col items-center justify-end h-full"
                  title={`${day}: ${total} calls`}
                >
                  <div
                    className="w-full rounded-t-sm bg-primary/70 transition-all group-hover:bg-primary"
                    style={{ height: `${heightPct}%`, minHeight: total > 0 ? 2 : 0 }}
                  />
                  {showLabel && (
                    <span className="absolute -bottom-5 left-1/2 -translate-x-1/2 text-[9px] text-muted-foreground whitespace-nowrap">
                      {label}
                    </span>
                  )}
                  <div className="absolute bottom-full mb-1 hidden group-hover:flex flex-col items-center z-10 pointer-events-none">
                    <div className="rounded bg-popover px-2 py-1 text-xs text-popover-foreground shadow border border-border whitespace-nowrap">
                      {day}: {total}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
