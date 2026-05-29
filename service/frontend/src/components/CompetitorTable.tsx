import { cn } from '@/lib/utils';
import type { MCPTool } from '@/types/database';

function scoreColor(v: number) {
  if (v > 0.6) return 'text-success';
  if (v > 0.3) return 'text-warning';
  return 'text-destructive';
}

function barColor(v: number) {
  if (v > 0.6) return 'bg-success';
  if (v > 0.3) return 'bg-warning';
  return 'bg-destructive';
}

const dims = ['clarity', 'disambiguation', 'parameter_coverage', 'boundary', 'stats', 'precision'] as const;
const dimLabels: Record<string, string> = {
  clarity: 'Clarity',
  disambiguation: 'Disambig',
  parameter_coverage: 'Params',
  boundary: 'Boundary',
  stats: 'Stats',
  precision: 'Precision',
};

export default function CompetitorTable({ tools, currentToolId }: { tools: MCPTool[]; currentToolId: string }) {
  const sorted = [...tools].sort((a, b) => (b.geo_score?.total ?? 0) - (a.geo_score?.total ?? 0));

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-secondary text-xs uppercase text-muted-foreground">
            <th className="px-3 py-2 text-left">Tool</th>
            <th className="px-3 py-2 text-right">Total</th>
            {dims.map(d => (
              <th key={d} className="px-3 py-2 text-right">{dimLabels[d]}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map(tool => {
            const isCurrent = tool.tool_id === currentToolId;
            return (
              <tr
                key={tool.tool_id}
                className={cn(
                  'border-b border-border transition-colors',
                  isCurrent && 'bg-primary/5 border-l-2 border-l-primary'
                )}
              >
                <td className="px-3 py-2 font-mono text-xs">{tool.tool_name}</td>
                <td className={cn('px-3 py-2 text-right font-mono font-medium', tool.geo_score ? scoreColor(tool.geo_score.total) : 'text-muted-foreground')}>
                  {tool.geo_score ? tool.geo_score.total.toFixed(2) : '—'}
                </td>
                {dims.map(d => {
                  const v = tool.geo_score?.[d];
                  return (
                    <td key={d} className="px-3 py-2 text-right">
                      {v !== undefined ? (
                        <div className="flex items-center justify-end gap-2">
                          <div className="h-1.5 w-10 rounded-full bg-secondary overflow-hidden">
                            <div className={cn('h-full rounded-full', barColor(v))} style={{ width: `${v * 100}%` }} />
                          </div>
                          <span className={cn('font-mono text-xs', scoreColor(v))}>{v.toFixed(2)}</span>
                        </div>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
