import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { config } from '@/lib/config';
import { getProviderDashboard } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';
import { cn } from '@/lib/utils';
import type { ProviderDashboardResponse, ProviderDashboardTool } from '@/types/database';

const dims = ['clarity', 'disambiguation', 'parameter_coverage', 'boundary', 'stats', 'precision'] as const;
const dimLabels: Record<string, string> = {
  clarity: 'Clarity', disambiguation: 'Disambig', parameter_coverage: 'Params',
  boundary: 'Boundary', stats: 'Stats', precision: 'Precision',
};

function barColor(v: number) { return v > 0.6 ? 'bg-success' : v > 0.3 ? 'bg-warning' : 'bg-destructive'; }
function scoreColor(v: number) { return v > 0.6 ? 'text-success' : v > 0.3 ? 'text-warning' : 'text-destructive'; }

interface ServerGroup {
  server_id: string;
  name: string;
  tools: ProviderDashboardTool[];
  avgGeo: number | null;
  needsImprovement: number;
}

function ServerGroupCard({ group }: { group: ServerGroup }) {
  const scored = group.tools.filter(t => t.geo_score);
  const unscored = group.tools.filter(t => !t.geo_score);
  const sortedScored = [...scored].sort((a, b) => (a.geo_score!.total) - (b.geo_score!.total));

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      {/* Server header */}
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border bg-secondary/30 px-5 py-4">
        <div>
          <h3 className="font-semibold text-foreground">{group.name}</h3>
          <p className="mt-0.5 font-mono text-xs text-muted-foreground">{group.server_id}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {group.avgGeo !== null && (
            <span className={cn('rounded-full px-2.5 py-0.5 text-xs font-medium', scoreColor(group.avgGeo), 'bg-secondary')}>
              Avg GEO {(group.avgGeo * 100).toFixed(0)}
            </span>
          )}
          <span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs text-muted-foreground">
            {group.tools.length} tools
          </span>
          {group.needsImprovement > 0 && (
            <span className="rounded-full bg-destructive/10 px-2.5 py-0.5 text-xs text-destructive">
              {group.needsImprovement} needs work
            </span>
          )}
        </div>
      </div>

      {/* Tool rows */}
      <div className="divide-y divide-border">
        {sortedScored.map(tool => (
          <div key={tool.tool_id} className="flex items-center gap-3 px-5 py-3 hover:bg-secondary/30 transition-colors">
            <Link
              to={`/dashboard/tools/${encodeURIComponent(tool.tool_id)}`}
              className="w-48 shrink-0 font-mono text-sm text-primary hover:underline truncate"
            >
              {tool.tool_name}
            </Link>
            <div className="flex flex-1 items-center gap-2">
              <div className="h-1.5 w-24 rounded-full bg-secondary overflow-hidden">
                <div
                  className={cn('h-full rounded-full', barColor(tool.geo_score!.total))}
                  style={{ width: `${tool.geo_score!.total * 100}%` }}
                />
              </div>
              <span className={cn('w-8 font-mono text-xs', scoreColor(tool.geo_score!.total))}>
                {(tool.geo_score!.total * 100).toFixed(0)}
              </span>
            </div>
            <Badge variant="outline" className="shrink-0 text-xs capitalize">
              {tool.index_status}
            </Badge>
          </div>
        ))}
        {unscored.map(tool => (
          <div key={tool.tool_id} className="flex items-center gap-3 px-5 py-3 hover:bg-secondary/30 transition-colors">
            <Link
              to={`/dashboard/tools/${encodeURIComponent(tool.tool_id)}`}
              className="w-48 shrink-0 font-mono text-sm text-primary hover:underline truncate"
            >
              {tool.tool_name}
            </Link>
            <div className="flex flex-1 items-center gap-2">
              <div className="h-1.5 w-24 rounded-full bg-secondary" />
              <span className="w-8 font-mono text-xs text-muted-foreground">—</span>
            </div>
            <Badge variant="outline" className="shrink-0 text-xs capitalize">
              {tool.index_status}
            </Badge>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { session, user } = useAuth();
  const accessToken = session?.access_token ?? '';
  const authIdentity = user?.id ?? accessToken ?? 'anonymous';
  const [searchParams] = useSearchParams();
  const registeredServerId = searchParams.get('server');
  const registrationPending = searchParams.get('registration') === 'pending';

  const { data, isLoading, isError } = useQuery({
    queryKey: ['dashboardTools', authIdentity],
    queryFn: () => getProviderDashboard(accessToken),
    enabled: config.api.isConfigured && !!accessToken,
  });

  const dashboard = data as ProviderDashboardResponse | undefined;
  const tools = dashboard?.tools ?? [];
  const summary = dashboard?.summary;

  const serverGroups = useMemo<ServerGroup[]>(() => {
    const map = new Map<string, { name: string; tools: ProviderDashboardTool[] }>();
    for (const tool of tools) {
      const entry = map.get(tool.server_id);
      if (entry) entry.tools.push(tool);
      else map.set(tool.server_id, { name: tool.server_name ?? tool.server_id, tools: [tool] });
    }
    return Array.from(map.entries()).map(([server_id, { name, tools: groupTools }]) => {
      const scored = groupTools.filter(t => t.geo_score);
      return {
        server_id,
        name,
        tools: groupTools,
        avgGeo: scored.length > 0
          ? scored.reduce((sum, t) => sum + (t.geo_score!.total), 0) / scored.length
          : null,
        needsImprovement: scored.filter(t => t.geo_score!.total < 0.5).length,
      };
    });
  }, [tools]);

  const worstTool = useMemo(() => {
    const scored = tools.filter(t => t.geo_score);
    if (!scored.length) return null;
    return scored.reduce((worst, t) => t.geo_score!.total < worst.geo_score!.total ? t : worst);
  }, [tools]);

  const weakestDimension = worstTool
    ? dims.reduce((low, dim) => worstTool.geo_score![dim] < worstTool.geo_score![low] ? dim : low, dims[0])
    : null;

  const summaryCards = [
    { label: 'Total Tools', value: summary?.total_tools ?? 0 },
    { label: 'Avg GEO Score', value: (summary?.avg_geo_score ?? 0).toFixed(2) },
    { label: 'Needs Improvement', value: summary?.needs_improvement ?? 0, color: (summary?.needs_improvement ?? 0) > 0 ? 'text-destructive' : undefined },
    { label: 'Fully Indexed', value: summary?.indexed_count ?? 0 },
  ];

  if (!config.api.isConfigured) {
    return <div className="mx-auto max-w-7xl px-4 py-10 text-muted-foreground">Could not load data. API is not configured yet.</div>;
  }
  if (!accessToken) {
    return <div className="mx-auto max-w-7xl px-4 py-10 text-muted-foreground">Please sign in to view your provider dashboard.</div>;
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-10">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Provider Dashboard</h1>
          <p className="mt-1 text-muted-foreground">Monitor and improve your tools&apos; search discoverability</p>
        </div>
        <Button asChild>
          <Link to="/dashboard/register">Register a Server</Link>
        </Button>
      </div>

      {registrationPending && registeredServerId && (
        <Alert className="mt-6 border-primary/30 bg-primary/5">
          <AlertTitle>Registration submitted</AlertTitle>
          <AlertDescription>
            <span className="font-mono">{registeredServerId}</span> is indexing now. Return here to watch it appear in your owned tools list.
          </AlertDescription>
        </Alert>
      )}

      {/* Summary */}
      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {summaryCards.map(c => (
          <div key={c.label} className="rounded-xl border border-border bg-card p-5">
            <p className="text-sm text-muted-foreground">{c.label}</p>
            <p className={cn('mt-1 text-2xl font-bold text-foreground', c.color)}>{isLoading ? '...' : c.value}</p>
          </div>
        ))}
      </div>

      {isError && <p className="mt-6 text-muted-foreground">Could not load data.</p>}

      {!isLoading && !isError && tools.length === 0 && (
        <div className="mt-8 rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
          <p>No owned servers yet. Register a server with your signed-in account to populate this dashboard.</p>
          <Button asChild className="mt-4">
            <Link to="/dashboard/register">Register your first server</Link>
          </Button>
        </div>
      )}

      {/* Worst-tool alert */}
      {!isLoading && worstTool && weakestDimension && (
        <Alert className="mt-8">
          <AlertTitle>Needs attention now</AlertTitle>
          <AlertDescription className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-muted-foreground">
              <span className="font-medium text-foreground">{worstTool.tool_name}</span> is your lowest-scoring tool.
              Start with <span className="font-medium text-foreground">{dimLabels[weakestDimension]}</span>, then review the detail page for action guidance.
            </p>
            <Button asChild size="sm" variant="outline">
              <Link to={`/dashboard/tools/${encodeURIComponent(worstTool.tool_id)}`}>Review tool detail</Link>
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {/* Server cards */}
      {!isLoading && serverGroups.length > 0 && (
        <div className="mt-8 space-y-4">
          {serverGroups.map(group => (
            <ServerGroupCard key={group.server_id} group={group} />
          ))}
        </div>
      )}
    </div>
  );
}
