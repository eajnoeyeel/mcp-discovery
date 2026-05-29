import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import type { SearchResult } from '@/types/database';

function scoreColor(score: number) {
  if (score > 0.7) return 'bg-success/20 text-success';
  if (score > 0.4) return 'bg-warning/20 text-warning';
  return 'bg-destructive/20 text-destructive';
}

export default function ResultCard({ result }: { result: SearchResult }) {
  const [expanded, setExpanded] = useState(false);
  const { tool, score, rank, reason, input_schema, score_breakdown } = result;

  return (
    <div className="rounded-xl border border-border bg-card p-6 transition-colors hover:border-muted-foreground/30">
      <div className="flex items-start gap-4">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-border text-sm font-bold text-muted-foreground">
          #{rank}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-lg text-foreground">{tool.tool_name}</span>
            <Badge variant="secondary" className="text-xs">{tool.server_id}</Badge>
            <span className={cn('rounded-full px-2 py-0.5 text-xs font-medium', scoreColor(score))}>
              {(score * 100).toFixed(0)}%
            </span>
          </div>
          {reason && <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{reason}</p>}
          <p className="mt-1 line-clamp-3 text-sm text-muted-foreground/70">{tool.description}</p>

          {score_breakdown && (
            <div className="mt-2 flex flex-wrap gap-2">
              {Object.entries(score_breakdown).map(([k, v]) => (
                <span key={k} className="text-xs text-muted-foreground">
                  {k}: <span className="font-mono">{(v as number).toFixed(2)}</span>
                </span>
              ))}
            </div>
          )}

          <button
            onClick={() => setExpanded(!expanded)}
            className="mt-3 flex items-center gap-1 text-xs text-primary hover:underline"
          >
            {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            {expanded ? 'Less' : 'More details'}
          </button>

          {expanded && (
            <div className="mt-3 space-y-3 border-t border-border pt-3">
              {input_schema && (
                <div>
                  <h4 className="mb-1 text-xs font-medium text-muted-foreground uppercase">Input Schema</h4>
                  <pre className="max-h-40 overflow-auto rounded-md bg-secondary p-3 text-xs text-foreground">
                    {JSON.stringify(input_schema, null, 2)}
                  </pre>
                </div>
              )}
              <Link
                to={`/tools/${encodeURIComponent(tool.tool_id)}`}
                className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
              >
                View Full Tool →
              </Link>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
