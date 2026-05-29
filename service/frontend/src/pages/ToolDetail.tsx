import { useParams, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { config } from '@/lib/config';
import { getToolDetail } from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { CopyButton } from '@/components/ui/copy-button';
import GEOScoreRadar from '@/components/GEOScoreRadar';
import { cn } from '@/lib/utils';
import type { GEOScore, ToolDetailResponse } from '@/types/database';
import { useState } from 'react';

const dims = ['clarity', 'disambiguation', 'parameter_coverage', 'boundary', 'stats', 'precision'] as const;
const dimLabels: Record<string, string> = {
  clarity: 'Clarity',
  disambiguation: 'Disambiguation',
  parameter_coverage: 'Parameter Coverage',
  boundary: 'Boundary',
  stats: 'Stats',
  precision: 'Precision',
};
const dimDescriptions: Record<string, string> = {
  clarity: 'Opening sentence clarity — primary action is obvious in one read.',
  disambiguation: 'Contrastive wording showing when this tool wins over alternatives.',
  parameter_coverage: 'Coverage of high-signal parameters, required inputs, and example values.',
  boundary: 'Explicit statement of what this tool cannot or should not handle.',
  stats: 'Concrete throughput, freshness, or coverage numbers.',
  precision: 'Exact domain terms and output nouns matching likely user intent.',
};

function barColor(v: number) {
  if (v > 0.6) return 'bg-success';
  if (v > 0.3) return 'bg-warning';
  return 'bg-destructive';
}

export default function ToolDetail() {
  const { toolId: rawToolId } = useParams<{ toolId: string }>();
  const toolId = decodeURIComponent(rawToolId || '');
  const [showRaw, setShowRaw] = useState(false);

  const { data, isLoading, isError } = useQuery({
    queryKey: ['tool', toolId],
    queryFn: () => getToolDetail(toolId),
    enabled: config.api.isConfigured && !!toolId,
  });

  if (!config.api.isConfigured) {
    return <div className="mx-auto max-w-7xl px-4 py-10 text-muted-foreground">API is not configured yet.</div>;
  }
  if (isLoading) return <div className="mx-auto max-w-7xl px-4 py-10"><div className="h-48 animate-pulse rounded-xl bg-card" /></div>;
  if (isError) {
    return (
      <div role="alert" className="mx-auto max-w-7xl px-4 py-10 text-sm text-destructive">
        Failed to load tool data. Please try again in a moment.
      </div>
    );
  }
  if (!data) return <div className="mx-auto max-w-7xl px-4 py-10 text-muted-foreground">Tool not found.</div>;

  const { tool, server } = data as ToolDetailResponse;

  const schema = tool.input_schema as Record<string, unknown> | null;
  const properties = schema?.properties as Record<string, { type?: string; description?: string }> | undefined;
  const required = (schema?.required as string[]) ?? [];
  const geo = tool.geo_score as GEOScore | null;

  return (
    <div className="mx-auto max-w-7xl px-4 py-10">
      {/* Breadcrumb */}
      <div className="mb-6 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        <Link to="/servers" className="hover:text-primary">Registry</Link>
        <span>/</span>
        {server && <Link to={`/servers/${server.server_id}`} className="hover:text-primary">{server.name}</Link>}
        <span>/</span>
        <span className="text-foreground">{tool.tool_name}</span>
      </div>

      {/* Header */}
      <div className="rounded-xl border border-border bg-card p-6">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="font-mono text-2xl font-bold text-foreground">{tool.tool_name}</h1>
          {server && (
            <Link to={`/servers/${server.server_id}`}>
              <Badge variant="secondary">{server.name}</Badge>
            </Link>
          )}
          <Badge variant="outline" className="capitalize">{tool.index_status}</Badge>
          {geo && (
            <span className="rounded-full bg-primary/10 px-3 py-1 text-sm font-medium text-primary">
              GEO {(geo.total * 100).toFixed(0)}
            </span>
          )}
        </div>
      </div>

      <div className="mt-8 grid gap-8 lg:grid-cols-5">
        {/* Left — 3/5 */}
        <div className="lg:col-span-3 space-y-8">
          {/* Description */}
          <section>
            <h2 className="text-lg font-semibold text-foreground mb-3">Description</h2>
            <div className="whitespace-pre-wrap text-sm text-muted-foreground">
              {tool.description || 'No description available.'}
            </div>
          </section>

          {/* Input Schema */}
          <section>
            <h2 className="text-lg font-semibold text-foreground mb-3">Input Schema</h2>
            {properties ? (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-xs uppercase text-muted-foreground">
                        <th className="px-3 py-2 text-left">Name</th>
                        <th className="px-3 py-2 text-left">Type</th>
                        <th className="px-3 py-2 text-left">Required</th>
                        <th className="px-3 py-2 text-left">Description</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(properties).map(([name, prop]) => (
                        <tr key={name} className="border-b border-border">
                          <td className="px-3 py-2 font-mono">{name}</td>
                          <td className="px-3 py-2"><Badge variant="secondary" className="text-xs">{prop.type || 'any'}</Badge></td>
                          <td className="px-3 py-2">{required.includes(name) ? <Badge className="text-xs">required</Badge> : <span className="text-muted-foreground text-xs">optional</span>}</td>
                          <td className="px-3 py-2 text-muted-foreground">{prop.description || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <button onClick={() => setShowRaw(!showRaw)} className="mt-3 text-xs text-primary hover:underline">
                  {showRaw ? 'Hide' : 'View'} Raw JSON
                </button>
                {showRaw && (
                  <div className="relative mt-2">
                    <pre className="max-h-60 overflow-auto rounded-md bg-secondary p-3 text-xs text-foreground">
                      {JSON.stringify(schema, null, 2)}
                    </pre>
                    <CopyButton
                      text={JSON.stringify(schema, null, 2)}
                      className="absolute right-2 top-2"
                    />
                  </div>
                )}
              </>
            ) : (
              <p className="text-sm text-muted-foreground">No input schema defined for this tool.</p>
            )}
          </section>
        </div>

        {/* Right — 2/5 */}
        <div className="lg:col-span-2 space-y-8">
          {geo ? (
            <section>
              <h2 className="text-lg font-semibold text-foreground mb-4">Description Quality (GEO Score)</h2>
              <div className="flex justify-center">
                <GEOScoreRadar geoScore={geo} />
              </div>
              <div className="mt-4 space-y-2">
                {dims.map(d => (
                  <div key={d} className="space-y-0.5">
                    <div className="flex items-center gap-3">
                      <span className="w-36 text-sm text-muted-foreground">{dimLabels[d]}</span>
                      <div className="flex-1 h-2 rounded-full bg-secondary overflow-hidden">
                        <div className={cn('h-full rounded-full', barColor(geo[d]))} style={{ width: `${geo[d] * 100}%` }} />
                      </div>
                      <span className="w-10 text-right font-mono text-sm text-foreground">{geo[d].toFixed(2)}</span>
                    </div>
                    <p className="pl-36 text-xs text-muted-foreground/70">{dimDescriptions[d]}</p>
                  </div>
                ))}
                <div className="border-t border-border pt-2 flex items-center gap-3">
                  <span className="w-36 font-semibold text-sm text-foreground">Total</span>
                  <div className="flex-1" />
                  <span className="w-10 text-right font-mono text-sm font-bold text-foreground">{geo.total.toFixed(2)}</span>
                </div>
              </div>
            </section>
          ) : (
            <div className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
              GEO Score not yet computed for this tool.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
