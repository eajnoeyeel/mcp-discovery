import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { config } from '@/lib/config';
import { getProviderDashboard } from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { AlertTriangle, Info, XCircle } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import type { ProviderDashboardResponse, ProviderDashboardTool, GEOScore } from '@/types/database';

const dims = ['clarity', 'disambiguation', 'parameter_coverage', 'boundary', 'stats', 'precision'] as const;
const dimLabels: Record<string, string> = {
  clarity: 'Clarity', disambiguation: 'Disambiguation', parameter_coverage: 'Parameter Coverage',
  boundary: 'Boundary', stats: 'Stats', precision: 'Precision',
};

type Severity = 'critical' | 'warning' | 'info';

interface Insight {
  severity: Severity;
  tool: ProviderDashboardTool;
  dimension: string;
  score: number;
  label: string;
}

function classifyInsights(tools: ProviderDashboardTool[]): Insight[] {
  const insights: Insight[] = [];
  for (const tool of tools) {
    if (!tool.geo_score) continue;
    const geo = tool.geo_score as GEOScore;
    for (const dim of dims) {
      const score = geo[dim];
      let severity: Severity | null = null;
      if (score < 0.3) severity = 'critical';
      else if (score < 0.6) severity = 'warning';
      else if (score < 0.75) severity = 'info';
      if (severity) {
        insights.push({ severity, tool, dimension: dim, score, label: dimLabels[dim] });
      }
    }
  }
  return insights;
}

const severityOrder: Record<Severity, number> = { critical: 0, warning: 1, info: 2 };

function SeverityIcon({ severity }: { severity: Severity }) {
  if (severity === 'critical') return <XCircle className="h-4 w-4 text-destructive" />;
  if (severity === 'warning') return <AlertTriangle className="h-4 w-4 text-warning" />;
  return <Info className="h-4 w-4 text-muted-foreground" />;
}

function severityVariant(severity: Severity): 'destructive' | 'secondary' | 'outline' {
  if (severity === 'critical') return 'destructive';
  if (severity === 'warning') return 'secondary';
  return 'outline';
}

export default function DashboardInsights() {
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
    return <div className="mx-auto max-w-7xl px-4 py-10 text-muted-foreground">Could not load insights.</div>;
  }

  const dashboard = data as ProviderDashboardResponse;
  const allInsights = classifyInsights(dashboard.tools);
  const sorted = [...allInsights].sort((a, b) => severityOrder[a.severity] - severityOrder[b.severity]);

  const counts = {
    critical: sorted.filter(i => i.severity === 'critical').length,
    warning: sorted.filter(i => i.severity === 'warning').length,
    info: sorted.filter(i => i.severity === 'info').length,
  };

  return (
    <div className="mx-auto max-w-7xl px-4 py-10">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Insights</h1>
          <p className="mt-1 text-muted-foreground">GEO score issues across all your tools</p>
        </div>
        <Link to="/dashboard" className="text-sm text-primary hover:underline">Back to Dashboard</Link>
      </div>

      {/* Summary counts */}
      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        {(['critical', 'warning', 'info'] as const).map(sev => (
          <div key={sev} className="rounded-xl border border-border bg-card p-5 flex items-center gap-3">
            <SeverityIcon severity={sev} />
            <div>
              <p className="text-sm text-muted-foreground capitalize">{sev}</p>
              <p className="text-2xl font-bold text-foreground">{counts[sev]}</p>
            </div>
          </div>
        ))}
      </div>

      {sorted.length === 0 ? (
        <div className="mt-8 rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
          No insights yet. All scored tools look good!
        </div>
      ) : (
        <div className="mt-8 space-y-2">
          {sorted.map((insight, idx) => (
            <div
              key={`${insight.tool.tool_id}-${insight.dimension}-${idx}`}
              className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-3"
            >
              <SeverityIcon severity={insight.severity} />
              <Badge variant={severityVariant(insight.severity)} className="text-xs capitalize w-16 justify-center">
                {insight.severity}
              </Badge>
              <Link
                to={`/dashboard/tools/${encodeURIComponent(insight.tool.tool_id)}`}
                className="font-mono text-sm text-primary hover:underline"
              >
                {insight.tool.tool_name}
              </Link>
              <span className="text-xs text-muted-foreground">{insight.tool.server_name ?? insight.tool.server_id}</span>
              <span className="flex-1" />
              <span className="text-sm text-muted-foreground">{insight.label}</span>
              <span className="font-mono text-sm font-medium text-foreground">{insight.score.toFixed(2)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
