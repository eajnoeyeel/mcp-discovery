import { cn } from '@/lib/utils';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface ClientStat {
  client_id: string;
  call_count: number;
  success_rate?: number;
}

interface ClientUsageBreakdownProps {
  data: ClientStat[];
}

const CLIENT_COLORS: Record<string, string> = {
  claude: 'bg-orange-500',
  gpt: 'bg-emerald-500',
  gemini: 'bg-blue-500',
};

const CLIENT_TEXT_COLORS: Record<string, string> = {
  claude: 'text-orange-600',
  gpt: 'text-emerald-600',
  gemini: 'text-blue-600',
};

function clientColor(clientId: string): string {
  const key = clientId.toLowerCase();
  for (const [prefix, color] of Object.entries(CLIENT_COLORS)) {
    if (key.includes(prefix)) return color;
  }
  return 'bg-secondary';
}

function clientTextColor(clientId: string): string {
  const key = clientId.toLowerCase();
  for (const [prefix, color] of Object.entries(CLIENT_TEXT_COLORS)) {
    if (key.includes(prefix)) return color;
  }
  return 'text-muted-foreground';
}

function clientLabel(clientId: string): string {
  const map: Record<string, string> = {
    claude: 'Claude',
    gpt: 'GPT',
    gemini: 'Gemini',
  };
  const key = clientId.toLowerCase();
  for (const [prefix, label] of Object.entries(map)) {
    if (key.includes(prefix)) return label;
  }
  return clientId;
}

export default function ClientUsageBreakdown({ data }: ClientUsageBreakdownProps) {
  const total = data.reduce((sum, d) => sum + d.call_count, 0);
  const sorted = [...data].sort((a, b) => b.call_count - a.call_count);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-semibold">Client Usage Breakdown</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {total === 0 ? (
          <p className="py-4 text-center text-sm text-muted-foreground">No data available</p>
        ) : (
          <>
            <div className="flex h-3 w-full overflow-hidden rounded-full">
              {sorted.map(({ client_id, call_count }) => {
                const pct = (call_count / total) * 100;
                return (
                  <div
                    key={client_id}
                    className={cn('h-full transition-all', clientColor(client_id))}
                    style={{ width: `${pct}%` }}
                    title={`${clientLabel(client_id)}: ${pct.toFixed(1)}%`}
                  />
                );
              })}
            </div>

            <div className="space-y-2">
              {sorted.map(({ client_id, call_count, success_rate }) => {
                const pct = total > 0 ? (call_count / total) * 100 : 0;
                return (
                  <div key={client_id} className="space-y-0.5">
                    <div className="flex items-center justify-between text-xs">
                      <div className="flex items-center gap-1.5">
                        <span className={cn('h-2 w-2 rounded-full', clientColor(client_id))} />
                        <span className="font-medium text-foreground">{clientLabel(client_id)}</span>
                        {success_rate != null && (
                          <span className="text-muted-foreground">
                            {(success_rate * 100).toFixed(0)}% success
                          </span>
                        )}
                      </div>
                      <span className={cn('font-mono font-medium', clientTextColor(client_id))}>
                        {pct.toFixed(1)}%
                        <span className="ml-1 text-muted-foreground font-normal">({call_count})</span>
                      </span>
                    </div>
                    <div className="h-1.5 w-full rounded-full bg-secondary overflow-hidden">
                      <div
                        className={cn('h-full rounded-full', clientColor(client_id))}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
