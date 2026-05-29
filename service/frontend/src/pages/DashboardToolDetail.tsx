import { Link, useParams } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, Clock3, XCircle } from 'lucide-react';
import { toast } from 'sonner';
import { config } from '@/lib/config';
import {
  applyProviderToolMetadataRefresh,
  getProviderToolDetail,
  getToolAnalytics,
  getToolInsights,
  previewProviderToolMetadataRefresh,
  updateProviderToolMetadata,
} from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import GEOScoreRadar from '@/components/GEOScoreRadar';
import CompetitorTable from '@/components/CompetitorTable';
import ProviderSimulationEvidence from '@/components/ProviderSimulationEvidence';
import WeeklyCallsChart from '@/components/WeeklyCallsChart';
import InsightCard from '@/components/InsightCard';
import MetadataEditorCard from '@/components/dashboard/MetadataEditorCard';
import MetadataRefreshDiffCard from '@/components/dashboard/MetadataRefreshDiffCard';
import Section from '@/components/dashboard/Section';
import Stat from '@/components/dashboard/Stat';
import StatGrid from '@/components/dashboard/StatGrid';
import { useAuth } from '@/contexts/AuthContext';
import { cn } from '@/lib/utils';
import type {
  GEOScore,
  ProviderToolDetailResponse,
  ToolMetadataDiffResult,
  UpdateProviderToolMetadataRequest,
} from '@/types/database';

const DEFAULT_CLIENT_APP_ID = 'dashboard-web';
const dims = ['clarity', 'disambiguation', 'parameter_coverage', 'boundary', 'stats', 'precision'] as const;
const dimLabels: Record<(typeof dims)[number], string> = {
  clarity: 'Clarity',
  disambiguation: 'Disambiguation',
  parameter_coverage: 'Parameter coverage',
  boundary: 'Boundary',
  stats: 'Stats',
  precision: 'Precision',
};
const suggestions: Record<(typeof dims)[number], string> = {
  clarity: 'Tighten the opening sentence so the primary action is obvious in one read.',
  disambiguation: 'Add contrastive wording about when this tool should win instead of nearby alternatives.',
  parameter_coverage: 'Spell out the high-signal parameters, required inputs, and example values providers expect.',
  boundary: 'State the limits clearly so clients know which requests belong somewhere else.',
  stats: 'Include concrete throughput, freshness, or coverage facts that improve trust at selection time.',
  precision: 'Use the exact domain terms, resource names, and output nouns that match likely user intent.',
};

interface AnalyticsDailyStat {
  day: string;
  call_count: number;
  client_id: string;
}

interface AnalyticsClientStat {
  client_id: string;
  call_count: number;
  success_rate?: number;
}

interface ToolInsight {
  severity: string;
  category: string;
  title: string;
  description: string;
  recommendation: string;
}

type StatusBannerTone = 'attention' | 'pending' | 'failed' | 'healthy';

function getAttentionState(indexStatus: string, geo: GEOScore | null) {
  if (indexStatus === 'pending') {
    return {
      title: 'Indexing in progress',
      description: 'GEO scoring and simulation evidence will fill in after processing completes.',
      icon: Clock3,
      tone: 'pending' as StatusBannerTone,
      ringClass: 'ring-primary/30 bg-primary/5',
      iconClass: 'text-primary',
    };
  }

  if (indexStatus === 'failed') {
    return {
      title: 'Indexing failed',
      description: 'The last indexing pass failed. Re-register the server or contact support.',
      icon: XCircle,
      tone: 'failed' as StatusBannerTone,
      ringClass: 'ring-destructive/40 bg-destructive/5',
      iconClass: 'text-destructive',
    };
  }

  if (!geo) {
    return {
      title: 'Waiting for the first GEO score',
      description: 'Indexing finished — the first score snapshot will land on the next scoring pass.',
      icon: Clock3,
      tone: 'pending' as StatusBannerTone,
      ringClass: 'ring-border bg-card',
      iconClass: 'text-muted-foreground',
    };
  }

  if (geo.total < 0.5) {
    return {
      title: 'Needs attention now',
      description: 'Underperforming today. Focus on the weakest dimensions before re-registering.',
      icon: AlertTriangle,
      tone: 'attention' as StatusBannerTone,
      ringClass: 'ring-warning/40 bg-warning/5',
      iconClass: 'text-warning',
    };
  }

  return {
    title: 'Healthy and ready to monitor',
    description: 'Scoring well today. Keep an eye on regressions in simulation evidence.',
    icon: CheckCircle2,
    tone: 'healthy' as StatusBannerTone,
    ringClass: 'ring-success/30 bg-success/5',
    iconClass: 'text-success',
  };
}

function buildHostedConnectHref(tool: ProviderToolDetailResponse['tool'], toolId: string): string | null {
  if (!tool.connect_supported || !tool.client_auth_mode || tool.client_auth_mode === 'none') {
    return null;
  }

  const params = new URLSearchParams({
    actor: 'client',
    server_id: tool.server_id,
    tool_name: tool.tool_name,
    auth_type: tool.client_auth_mode,
    return_to: `/dashboard/tools/${toolId}`,
  });

  if (tool.connection_reuse_scope === 'client_app') {
    params.set('client_app_id', DEFAULT_CLIENT_APP_ID);
  }

  return `/connect?${params.toString()}`;
}

function getHostedConnectLabel(tool: ProviderToolDetailResponse['tool']): string {
  if (tool.client_auth_mode === 'api_key') {
    return 'Open API key connect shell';
  }
  return 'Open hosted connect';
}

function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return 'Never';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return 'Never';
  const diffSec = Math.round((Date.now() - then) / 1000);
  if (diffSec < 60) return 'just now';
  if (diffSec < 3600) return `${Math.round(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.round(diffSec / 3600)}h ago`;
  return `${Math.round(diffSec / 86400)}d ago`;
}

function formatReachability(status: string | null | undefined): { label: string; tone: 'positive' | 'negative' | 'neutral' } {
  if (status === 'healthy') return { label: 'Healthy', tone: 'positive' };
  if (status === 'degraded') return { label: 'Degraded', tone: 'negative' };
  if (status === 'unreachable') return { label: 'Down', tone: 'negative' };
  return { label: 'Unknown', tone: 'neutral' };
}

export default function DashboardToolDetail() {
  const { toolId: rawToolId } = useParams<{ toolId: string }>();
  const toolId = decodeURIComponent(rawToolId || '');
  const { session, user } = useAuth();
  const accessToken = session?.access_token ?? '';
  const authIdentity = user?.id ?? accessToken ?? 'anonymous';
  const queryClient = useQueryClient();
  const detailQueryKey = ['dashTool', authIdentity, toolId] as const;
  const analyticsQueryKey = ['toolAnalytics', authIdentity, toolId] as const;
  const insightsQueryKey = ['toolInsights', authIdentity, toolId] as const;
  const activePreviewKey = `${authIdentity}:${toolId}`;
  const [previewState, setPreviewState] = useState<{ key: string; data: ToolMetadataDiffResult } | null>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: detailQueryKey,
    queryFn: () => getProviderToolDetail(accessToken, toolId),
    enabled: config.api.isConfigured && !!toolId && !!accessToken,
  });

  const { data: analyticsData } = useQuery({
    queryKey: analyticsQueryKey,
    queryFn: () => getToolAnalytics(toolId, accessToken),
    enabled: config.api.isConfigured && !!toolId && !!accessToken,
  });

  const { data: insightsData } = useQuery({
    queryKey: insightsQueryKey,
    queryFn: () => getToolInsights(toolId, accessToken),
    enabled: config.api.isConfigured && !!toolId && !!accessToken,
  });

  const metadataMutation = useMutation({
    mutationFn: (payload: UpdateProviderToolMetadataRequest) => updateProviderToolMetadata(accessToken, toolId, payload),
    onSuccess: async () => {
      toast.success('Published metadata saved');
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: detailQueryKey }),
        queryClient.invalidateQueries({ queryKey: analyticsQueryKey }),
        queryClient.invalidateQueries({ queryKey: insightsQueryKey }),
        queryClient.invalidateQueries({ queryKey: ['dashboardTools'] }),
      ]);
    },
    onError: (error: Error) => {
      toast.error(error.message ?? 'Failed to save published metadata');
    },
  });

  const previewMutation = useMutation({
    mutationFn: () => previewProviderToolMetadataRefresh(accessToken, toolId),
    onSuccess: (preview) => {
      setPreviewState({ key: activePreviewKey, data: preview });
    },
    onError: (error: Error) => {
      toast.error(error.message ?? 'Failed to preview upstream metadata');
    },
  });

  const resetPreviewMutation = previewMutation.reset;
  const activePreview = previewState?.key === activePreviewKey ? previewState.data : null;

  useEffect(() => {
    setPreviewState(null);
    resetPreviewMutation();
  }, [activePreviewKey, resetPreviewMutation]);

  const refreshMutation = useMutation({
    mutationFn: async (strategy: 'keep' | 'adopt') => {
      const preview = activePreview ?? undefined;
      const currentTool = data?.tool;
      if (!preview) {
        throw new Error('Preview the upstream diff before applying it.');
      }
      if (!currentTool) {
        throw new Error('Tool detail is not available yet.');
      }

      const relevantDiff = [...preview.changed, ...preview.added, ...preview.removed].find(
        (entry) => entry.tool_name === currentTool.tool_name,
      );
      const publishedDescription = relevantDiff?.effective_description ?? currentTool.description ?? '';
      const upstreamDescription = relevantDiff?.upstream_description ?? '';

      const applied = await applyProviderToolMetadataRefresh(accessToken, toolId);

      if (strategy === 'keep' && publishedDescription && applied.tool.description !== publishedDescription) {
        await updateProviderToolMetadata(accessToken, toolId, { description: publishedDescription });
      }

      if (strategy === 'adopt' && upstreamDescription && applied.tool.description !== upstreamDescription) {
        await updateProviderToolMetadata(accessToken, toolId, { description: upstreamDescription });
      }

      return applied;
    },
    onSuccess: async (_result, strategy) => {
      setPreviewState(null);
      previewMutation.reset();
      toast.success(
        strategy === 'keep'
          ? 'Upstream metadata refreshed while keeping the published copy.'
          : 'Published metadata updated from the upstream reference.',
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: detailQueryKey }),
        queryClient.invalidateQueries({ queryKey: analyticsQueryKey }),
        queryClient.invalidateQueries({ queryKey: insightsQueryKey }),
        queryClient.invalidateQueries({ queryKey: ['dashboardTools'] }),
      ]);
    },
    onError: (error: Error) => {
      toast.error(error.message ?? 'Failed to apply upstream metadata refresh');
    },
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
  if (isError) {
    return (
      <div role="alert" className="mx-auto max-w-7xl px-4 py-10 text-sm text-destructive">
        Failed to load tool. Metadata edits are disabled until the detail page loads successfully.
      </div>
    );
  }
  if (!data) {
    return <div className="mx-auto max-w-7xl px-4 py-10 text-muted-foreground">Tool not found.</div>;
  }

  const { tool, competitors, simulations } = data as ProviderToolDetailResponse;
  const analytics = analyticsData as { daily_stats?: AnalyticsDailyStat[]; client_stats?: AnalyticsClientStat[] } | undefined;
  const insights = insightsData as { insights?: ToolInsight[] } | undefined;
  const geo = tool.geo_score as GEOScore | null;
  const attention = getAttentionState(tool.index_status, geo);
  const AttentionIcon = attention.icon;
  const hostedConnectHref = buildHostedConnectHref(tool, toolId);
  const weakestDimensions = geo
    ? [...dims]
        .sort((left, right) => geo[left] - geo[right])
        .slice(0, 3)
        .map((dimension) => ({
          dimension,
          label: dimLabels[dimension],
          score: geo[dimension],
          suggestion: suggestions[dimension],
        }))
    : [];

  // Conditional thresholds — only render sections with meaningful data
  const timesExposed = tool.times_exposed ?? 0;
  const showSelection = timesExposed >= 50;
  const dailyStats = analytics?.daily_stats ?? [];
  const nonZeroDays = dailyStats.filter((d) => d.call_count > 0).length;
  const showActivity = nonZeroDays >= 7;
  const insightsList = insights?.insights ?? [];
  const showInsights = insightsList.length > 0;

  const reach = formatReachability(tool.reachability_status);

  return (
    <div className="mx-auto max-w-7xl space-y-14 px-4 py-10">
      {/* PERSISTENT HEADER */}
      <header className="space-y-6">
        <nav className="flex items-center gap-2 text-sm text-muted-foreground" aria-label="Breadcrumb">
          <Link to="/dashboard" className="transition-colors hover:text-foreground">Dashboard</Link>
          <span aria-hidden>/</span>
          <span className="text-foreground">{tool.tool_name}</span>
        </nav>

        <div className="space-y-4">
          <h1 className="font-semibold text-[44px] leading-[1.05] tracking-[-0.04em] text-foreground">
            {tool.tool_name}
          </h1>

          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary" className="font-mono">
              {tool.server_name ?? tool.server_id}
            </Badge>
            <Badge variant="outline" className="capitalize">
              {tool.index_status}
            </Badge>
            {geo && (
              <span
                className={cn(
                  'inline-flex items-center gap-2 rounded-full px-3.5 py-1 text-sm font-semibold tabular-nums',
                  geo.total >= 0.7
                    ? 'bg-success/10 text-success'
                    : geo.total >= 0.5
                      ? 'bg-primary/10 text-primary'
                      : 'bg-warning/10 text-warning',
                )}
              >
                GEO {(geo.total * 100).toFixed(0)}
              </span>
            )}
          </div>
        </div>

        {/* Single-line status banner */}
        <div
          className={cn(
            'flex items-center gap-3 rounded-[14px] px-5 py-3.5 ring-1',
            attention.ringClass,
          )}
          role={attention.tone === 'attention' || attention.tone === 'failed' ? 'alert' : undefined}
        >
          <AttentionIcon className={cn('h-4 w-4 shrink-0', attention.iconClass)} />
          <span className="text-sm font-medium text-foreground">{attention.title}</span>
          <span className="text-sm text-muted-foreground">— {attention.description}</span>
        </div>

        {hostedConnectHref && (
          <div className="flex items-center justify-between rounded-[14px] bg-card px-5 py-4 ring-1 ring-border/60">
            <div>
              <p className="text-sm font-medium text-foreground">Hosted connect shell</p>
              <p className="text-sm text-muted-foreground">
                Rehearse the client-side hosted connect flow with this tool&apos;s auth policy.
              </p>
            </div>
            <Button asChild variant="outline" className="rounded-full">
              <Link to={hostedConnectHref}>{getHostedConnectLabel(tool)}</Link>
            </Button>
          </div>
        )}
      </header>

      {/* 1. DESCRIPTION QUALITY */}
      <Section
        eyebrow="QUALITY"
        title="Description Quality"
        description="The 6-dimension GEO score breaks down how well your description guides selection. The three weakest dimensions are the highest-leverage edits."
      >
        {geo ? (
          <div className="grid gap-8 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)] lg:items-start">
            <div className="flex justify-center rounded-[14px] bg-card p-6 ring-1 ring-border/60">
              <GEOScoreRadar geoScore={geo} />
            </div>
            <div className="space-y-3">
              <h3 className="text-base font-medium text-foreground">Weakest dimensions</h3>
              {weakestDimensions.map((item) => (
                <div
                  key={item.dimension}
                  className="rounded-[14px] bg-card p-5 ring-1 ring-border/60"
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-medium text-foreground">{item.label}</span>
                    <span className="font-mono text-sm tabular-nums text-muted-foreground">
                      {item.score.toFixed(2)}
                    </span>
                  </div>
                  <p className="mt-2 text-sm text-muted-foreground">{item.suggestion}</p>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="rounded-[14px] bg-card p-6 ring-1 ring-border/60 text-sm text-muted-foreground">
            A detailed GEO breakdown will appear once the first scoring run completes.
          </div>
        )}
      </Section>

      {/* 2. CURRENT DESCRIPTION */}
      <Section
        eyebrow="COPY"
        title="Current Description"
        description="The published copy MLP exposes for tool selection."
      >
        <pre className="whitespace-pre-wrap rounded-[14px] bg-background p-6 font-mono text-sm leading-relaxed text-foreground ring-1 ring-border/60">
          {tool.description?.trim() || 'No published description yet.'}
        </pre>
        <p className="text-xs text-muted-foreground">
          This is the copy providers edit before re-registering.
        </p>
      </Section>

      {/* 3. INDEXING & HEALTH */}
      <Section
        eyebrow="OPERATIONS"
        title="Indexing & Health"
        description="Where this tool stands in the pipeline right now."
      >
        <StatGrid cols={3}>
          <Stat
            label="Index Status"
            value={tool.index_status.charAt(0).toUpperCase() + tool.index_status.slice(1)}
          />
          <Stat
            label="Last Indexed"
            value={formatRelativeTime(tool.last_indexed_at ?? tool.metadata_last_fetched_at)}
          />
          <Stat
            label="Reachability"
            value={reach.label}
            unit={tool.reachability_latency_ms ? `${Math.round(tool.reachability_latency_ms)}ms` : undefined}
            delta={
              tool.reachability_status
                ? { value: reach.label, direction: reach.tone === 'positive' ? 'up' : reach.tone === 'negative' ? 'down' : 'flat', tone: reach.tone }
                : undefined
            }
          />
        </StatGrid>
      </Section>

      {/* CONDITIONAL: SELECTION */}
      {showSelection && (
        <Section
          eyebrow="SELECTION"
          title="Selection"
          description="How often this tool wins when exposed to a query."
        >
          <StatGrid cols={3}>
            <Stat
              label="Times Exposed"
              value={timesExposed.toLocaleString()}
            />
            <Stat
              label="Selection Rate"
              value={tool.selection_rate != null ? `${Math.round((tool.selection_rate ?? 0) * 100)}` : '—'}
              unit={tool.selection_rate != null ? '%' : undefined}
            />
            <Stat
              label="Conversion"
              value={
                tool.times_selected != null && timesExposed > 0
                  ? `${Math.round(((tool.times_selected ?? 0) / timesExposed) * 100)}`
                  : '—'
              }
              unit={tool.times_selected != null && timesExposed > 0 ? '%' : undefined}
            />
          </StatGrid>
        </Section>
      )}

      {/* CONDITIONAL: ACTIVITY */}
      {showActivity && (
        <Section
          eyebrow="ACTIVITY"
          title="Activity"
          description="Daily call volume across the last 30 days."
        >
          <div className="rounded-[14px] bg-card p-6 ring-1 ring-border/60">
            <WeeklyCallsChart data={dailyStats} />
          </div>
        </Section>
      )}

      {/* CONDITIONAL: INSIGHTS */}
      {showInsights && (
        <Section
          eyebrow="INSIGHTS"
          title="Why Not Selected?"
          description="Detected issues from the most recent simulation runs."
        >
          <div className="space-y-3">
            {insightsList.map((insight, index) => (
              <InsightCard key={index} insight={insight} />
            ))}
          </div>
        </Section>
      )}

      {/* SIMULATION EVIDENCE — required by tests when simulations exist or pending state */}
      <ProviderSimulationEvidence simulations={simulations} />

      {/* PUBLISHED METADATA EDITOR — required by tests */}
      <Section
        eyebrow="METADATA"
        title="Published Metadata"
        description="Edit the published copy and review the upstream reference snapshot side-by-side."
      >
        <MetadataEditorCard
          tool={tool}
          onSave={(payload) => metadataMutation.mutateAsync(payload)}
          isSaving={metadataMutation.isPending}
        />
      </Section>

      {/* UPSTREAM REFRESH — required by tests */}
      <Section
        eyebrow="UPSTREAM"
        title="Upstream Refresh"
        description="Pull a fresh upstream snapshot, review the diff, then keep or adopt."
      >
        <MetadataRefreshDiffCard
          tool={tool}
          preview={activePreview}
          onPreview={() => previewMutation.mutateAsync()}
          onApply={(strategy) => refreshMutation.mutateAsync(strategy)}
          isPreviewing={previewMutation.isPending}
          isApplying={refreshMutation.isPending}
        />
      </Section>

      {/* SAME-SERVER COMPARISON — required by tests (with empty state) */}
      <Section
        eyebrow="PEERS"
        title="Same-server comparison"
        description="How this tool compares against its server siblings."
      >
        {competitors.length > 0 ? (
          <div className="rounded-[14px] bg-card p-6 ring-1 ring-border/60">
            <CompetitorTable tools={competitors} currentToolId={tool.tool_id} />
          </div>
        ) : (
          <div className="rounded-[14px] bg-card p-6 ring-1 ring-border/60 text-sm text-muted-foreground">
            No same-server comparison tools yet. Use the weakest dimensions and simulation evidence above as the next-action guide.
          </div>
        )}
      </Section>
    </div>
  );
}
