import { cn } from '@/lib/utils';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

interface Insight {
  severity: string;
  category: string;
  title: string;
  description: string;
  recommendation: string;
}

interface InsightCardProps {
  insight: Insight;
}

type Severity = 'critical' | 'warning' | 'info';

function normalizeSeverity(severity: string): Severity {
  const s = severity.toLowerCase();
  if (s === 'critical') return 'critical';
  if (s === 'warning') return 'warning';
  return 'info';
}

const SEVERITY_BADGE: Record<Severity, string> = {
  critical: 'bg-destructive/10 text-destructive border-destructive/20',
  warning: 'bg-warning/10 text-warning border-warning/20',
  info: 'bg-blue-500/10 text-blue-600 border-blue-500/20',
};

const SEVERITY_BORDER: Record<Severity, string> = {
  critical: 'border-l-destructive',
  warning: 'border-l-warning',
  info: 'border-l-blue-500',
};

const SEVERITY_LABEL: Record<Severity, string> = {
  critical: 'Critical',
  warning: 'Warning',
  info: 'Info',
};

export default function InsightCard({ insight }: InsightCardProps) {
  const severity = normalizeSeverity(insight.severity);

  return (
    <Card className={cn('border-l-4', SEVERITY_BORDER[severity])}>
      <CardContent className="p-4 space-y-2">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 flex-wrap">
            <Badge
              variant="outline"
              className={cn('text-[10px] font-semibold uppercase tracking-wide', SEVERITY_BADGE[severity])}
            >
              {SEVERITY_LABEL[severity]}
            </Badge>
            <Badge variant="secondary" className="text-[10px]">
              {insight.category}
            </Badge>
          </div>
        </div>

        <h4 className="text-sm font-semibold text-foreground leading-snug">{insight.title}</h4>

        <p className="text-xs text-muted-foreground leading-relaxed">{insight.description}</p>

        <div className="rounded-md bg-secondary/60 px-3 py-2">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-0.5">
            Recommendation
          </p>
          <p className="text-xs text-foreground leading-relaxed">{insight.recommendation}</p>
        </div>
      </CardContent>
    </Card>
  );
}
