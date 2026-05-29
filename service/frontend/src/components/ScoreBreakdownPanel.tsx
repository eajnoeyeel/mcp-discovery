import { cn } from '@/lib/utils';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface ScoreBreakdownPanelProps {
  relevance?: number;
  operability?: number;
  quality?: number;
  freshness?: number;
}

interface ScoreRow {
  label: string;
  key: keyof ScoreBreakdownPanelProps;
  weight: number;
  weightLabel: string;
}

const rows: ScoreRow[] = [
  { label: 'Relevance', key: 'relevance', weight: 0.6, weightLabel: '60%' },
  { label: 'Operability', key: 'operability', weight: 0.25, weightLabel: '25%' },
  { label: 'Quality', key: 'quality', weight: 0.1, weightLabel: '10%' },
  { label: 'Freshness', key: 'freshness', weight: 0.05, weightLabel: '5%' },
];

function barColor(v: number) {
  if (v > 0.6) return 'bg-success';
  if (v > 0.3) return 'bg-warning';
  return 'bg-destructive';
}

function textColor(v: number) {
  if (v > 0.6) return 'text-success';
  if (v > 0.3) return 'text-warning';
  return 'text-destructive';
}

function computeFinalScore(props: ScoreBreakdownPanelProps): number {
  const { relevance = 0, operability = 0, quality = 0, freshness = 0 } = props;
  return relevance * 0.6 + operability * 0.25 + quality * 0.1 + freshness * 0.05;
}

export default function ScoreBreakdownPanel(props: ScoreBreakdownPanelProps) {
  const finalScore = computeFinalScore(props);

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold">Score Breakdown</CardTitle>
          <span className={cn('font-mono text-lg font-bold', textColor(finalScore))}>
            {finalScore.toFixed(2)}
          </span>
        </div>
        <p className="text-xs text-muted-foreground font-mono">
          relevance×0.60 + operability×0.25 + quality×0.10 + freshness×0.05
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        {rows.map(({ label, key, weightLabel }) => {
          const value = props[key] ?? 0;
          return (
            <div key={key} className="space-y-1">
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-foreground">{label}</span>
                  <span className="rounded-full bg-secondary px-1.5 py-0.5 text-[10px] text-muted-foreground">
                    {weightLabel}
                  </span>
                </div>
                <span className={cn('font-mono font-medium', textColor(value))}>
                  {value.toFixed(2)}
                </span>
              </div>
              <div className="h-2 w-full rounded-full bg-secondary overflow-hidden">
                <div
                  className={cn('h-full rounded-full transition-all', barColor(value))}
                  style={{ width: `${value * 100}%` }}
                />
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
