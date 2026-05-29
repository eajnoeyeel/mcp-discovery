import { Badge } from '@/components/ui/badge';
import type { ProviderToolSimulation } from '@/types/database';

function parseNumber(value: number | string | null): number | null {
  if (value === null) {
    return null;
  }

  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatCount(value: number | string): string {
  const parsed = parseNumber(value);
  if (parsed === null) {
    return String(value);
  }

  return parsed.toLocaleString();
}

function formatPercent(value: number | null): string {
  if (value === null) {
    return '—';
  }

  return `${Math.round(value * 100)}%`;
}

function formatLatency(value: number | null): string {
  if (value === null) {
    return '—';
  }

  return `${value.toFixed(1)} ms`;
}

function formatRatio(numerator: number | null, denominator: number | null): string {
  if (numerator === null || denominator === null || denominator <= 0) {
    return '—';
  }

  return `${Math.round((numerator / denominator) * 100)}%`;
}

export default function ProviderSimulationEvidence({ simulations }: { simulations: ProviderToolSimulation[] }) {
  const sample = simulations[0];

  return (
    <section className="rounded-xl border border-border bg-card p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-foreground">Simulation evidence</h2>
          <p className="text-sm text-muted-foreground">
            Aggregated query-log evidence for how often this tool wins selection today.
          </p>
        </div>
        {sample && <Badge variant="secondary">{formatCount(sample.query_count)} logged searches</Badge>}
      </div>

      {!sample ? (
        <p className="text-sm text-muted-foreground">
          Simulation evidence will appear after query logs accumulate for this tool.
        </p>
      ) : (
        <div className="grid gap-4 md:grid-cols-3">
          <div className="rounded-lg border border-border bg-secondary/30 p-4">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Average confidence</p>
            <p className="mt-2 font-mono text-2xl font-semibold text-foreground">
              {formatPercent(parseNumber(sample.avg_confidence))}
            </p>
            <p className="mt-2 text-xs text-muted-foreground">Higher values mean the tool wins with less ambiguity.</p>
          </div>

          <div className="rounded-lg border border-border bg-secondary/30 p-4">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">High-confidence share</p>
            <p className="mt-2 font-mono text-2xl font-semibold text-foreground">
              {formatRatio(parseNumber(sample.high_confidence_count), parseNumber(sample.query_count))}
            </p>
            <p className="mt-2 text-xs text-muted-foreground">
              {formatCount(sample.high_confidence_count)} of {formatCount(sample.query_count)} logged searches were high-confidence.
            </p>
          </div>

          <div className="rounded-lg border border-border bg-secondary/30 p-4">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Average latency</p>
            <p className="mt-2 font-mono text-2xl font-semibold text-foreground">
              {formatLatency(parseNumber(sample.avg_latency_ms))}
            </p>
            <p className="mt-2 text-xs text-muted-foreground">Use this to spot speed trade-offs while improving selection quality.</p>
          </div>
        </div>
      )}
    </section>
  );
}
