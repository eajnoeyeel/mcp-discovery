import { useParams, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { config } from '@/lib/config';
import { getServerDetail } from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import type { ServerDetailResponse } from '@/types/database';

const statusColors = { indexed: 'bg-success', pending: 'bg-warning', failed: 'bg-destructive' };

export default function ServerDetail() {
  const { serverId } = useParams<{ serverId: string }>();

  const { data, isLoading, isError } = useQuery({
    queryKey: ['server', serverId],
    queryFn: () => getServerDetail(serverId!),
    enabled: config.api.isConfigured && !!serverId,
  });

  if (!config.api.isConfigured) {
    return <div className="mx-auto max-w-7xl px-4 py-10 text-muted-foreground">API is not configured yet.</div>;
  }

  if (isLoading) {
    return <div className="mx-auto max-w-7xl px-4 py-10"><div className="h-48 animate-pulse rounded-xl bg-card" /></div>;
  }

  if (isError || !data) {
    return <div className="mx-auto max-w-7xl px-4 py-10 text-muted-foreground">Could not load server data.</div>;
  }

  const { server, tools } = data as ServerDetailResponse;

  return (
    <div className="mx-auto max-w-7xl px-4 py-10">
      {/* Breadcrumb */}
      <div className="mb-6 flex items-center gap-2 text-sm text-muted-foreground">
        <Link to="/servers" className="hover:text-primary">Registry</Link>
        <span>/</span>
        <span className="text-foreground">{server.name}</span>
      </div>

      {/* Header */}
      <div className="rounded-xl border border-border bg-card p-6">
        <div className="flex items-start gap-3">
          <h1 className="text-2xl font-bold text-foreground">{server.name}</h1>
        </div>
        {server.description && <p className="mt-2 text-muted-foreground">{server.description}</p>}
        <div className="mt-4 flex flex-wrap items-center gap-3">
          {server.url && (
            <a href={server.url} target="_blank" rel="noopener noreferrer" className="text-sm text-primary hover:underline">
              {server.url}
            </a>
          )}
          {server.tags?.map(tag => (
            <Badge key={tag} variant="secondary" className="text-xs">{tag}</Badge>
          ))}
          <span className="text-xs text-muted-foreground">Created {new Date(server.created_at).toLocaleDateString()}</span>
        </div>
      </div>

      {/* Tools */}
      <h2 className="mt-8 text-lg font-semibold text-foreground">Tools ({tools?.length ?? 0})</h2>
      <div className="mt-4 space-y-2">
        {tools?.map(tool => (
          <Link
            key={tool.tool_id}
            to={`/tools/${encodeURIComponent(tool.tool_id)}`}
            className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-3 transition-colors hover:border-muted-foreground/30"
          >
            <span className="font-mono text-sm text-foreground">{tool.tool_name}</span>
            <span className="flex-1 truncate text-sm text-muted-foreground">{tool.description || 'No description'}</span>
            {tool.geo_score && (
              <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                {(tool.geo_score.total * 100).toFixed(0)}
              </span>
            )}
            <span className={cn('h-2 w-2 rounded-full', statusColors[tool.index_status])} />
          </Link>
        ))}
      </div>
    </div>
  );
}
