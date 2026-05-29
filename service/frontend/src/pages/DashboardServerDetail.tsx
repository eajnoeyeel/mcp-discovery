import { useParams, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { config } from '@/lib/config';
import { getProviderDashboard } from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { useAuth } from '@/contexts/AuthContext';
import type { ProviderDashboardResponse, ProviderDashboardTool } from '@/types/database';

function scoreColor(v: number) { return v > 0.6 ? 'text-success' : v > 0.3 ? 'text-warning' : 'text-destructive'; }

export default function DashboardServerDetail() {
  const { serverId } = useParams<{ serverId: string }>();
  const { session, user } = useAuth();
  const accessToken = session?.access_token ?? '';
  const authIdentity = user?.id ?? accessToken ?? 'anonymous';

  const { data, isLoading, isError } = useQuery({
    queryKey: ['dashboardTools', authIdentity],
    queryFn: () => getProviderDashboard(accessToken),
    enabled: config.api.isConfigured && !!accessToken,
  });

  if (!config.api.isConfigured) {
    return <div className="mx-auto max-w-7xl px-4 py-10 text-muted-foreground">API is not configured yet.</div>;
  }
  if (!accessToken) {
    return <div className="mx-auto max-w-7xl px-4 py-10 text-muted-foreground">Please sign in to view this page.</div>;
  }
  if (isLoading) {
    return <div className="mx-auto max-w-7xl px-4 py-10"><div className="h-48 animate-pulse rounded-xl bg-card" /></div>;
  }
  if (isError || !data) {
    return <div className="mx-auto max-w-7xl px-4 py-10 text-muted-foreground">Could not load server data.</div>;
  }

  const dashboard = data as ProviderDashboardResponse;
  const serverTools = dashboard.tools.filter(t => t.server_id === serverId);
  const serverName = serverTools[0]?.server_name ?? serverId;

  const sorted = [...serverTools].sort(
    (a: ProviderDashboardTool, b: ProviderDashboardTool) =>
      (b.geo_score?.total ?? 0) - (a.geo_score?.total ?? 0),
  );

  return (
    <div className="mx-auto max-w-7xl px-4 py-10">
      {/* Breadcrumb */}
      <div className="mb-6 flex items-center gap-2 text-sm text-muted-foreground">
        <Link to="/dashboard" className="hover:text-primary">Dashboard</Link>
        <span>/</span>
        <span className="text-foreground">{serverName}</span>
      </div>

      {/* Header */}
      <div className="rounded-xl border border-border bg-card p-6">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-bold text-foreground">{serverName}</h1>
          <Badge variant="secondary">{serverTools.length} tools</Badge>
          <Badge variant="outline" className="font-mono text-xs">{serverId}</Badge>
        </div>
      </div>

      {/* Tools table */}
      {sorted.length === 0 ? (
        <div className="mt-8 rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
          No tools found for this server.
        </div>
      ) : (
        <div className="mt-8 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-secondary text-xs uppercase text-muted-foreground">
                <th className="px-3 py-2 text-left">Tool</th>
                <th className="px-3 py-2 text-left">Description</th>
                <th className="px-3 py-2 text-right">GEO Score</th>
                <th className="px-3 py-2 text-center">Status</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map(tool => (
                <tr key={tool.tool_id} className="border-b border-border hover:bg-secondary/50 transition-colors">
                  <td className="px-3 py-2">
                    <Link
                      to={`/dashboard/tools/${encodeURIComponent(tool.tool_id)}`}
                      className="font-mono text-primary hover:underline"
                    >
                      {tool.tool_name}
                    </Link>
                  </td>
                  <td className="px-3 py-2 max-w-xs truncate text-muted-foreground">
                    {tool.description ?? 'No description'}
                  </td>
                  <td className={cn('px-3 py-2 text-right font-mono font-medium', tool.geo_score ? scoreColor(tool.geo_score.total) : 'text-muted-foreground')}>
                    {tool.geo_score ? tool.geo_score.total.toFixed(2) : '—'}
                  </td>
                  <td className="px-3 py-2 text-center">
                    <Badge
                      variant={tool.index_status === 'indexed' ? 'default' : tool.index_status === 'failed' ? 'destructive' : 'secondary'}
                      className="text-xs"
                    >
                      {tool.index_status}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
