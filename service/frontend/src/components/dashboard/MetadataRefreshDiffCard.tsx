import { AlertTriangle, RefreshCw } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import type { ProviderToolDetailResponse, ToolMetadataDiffEntry, ToolMetadataDiffResult } from '@/types/database';

interface MetadataRefreshDiffCardProps {
  tool: ProviderToolDetailResponse['tool'];
  preview: ToolMetadataDiffResult | null;
  onPreview: () => Promise<unknown>;
  onApply: (strategy: 'keep' | 'adopt') => Promise<unknown>;
  isPreviewing?: boolean;
  isApplying?: boolean;
}

function findRelevantDiff(toolName: string, preview: ToolMetadataDiffResult | null): ToolMetadataDiffEntry | null {
  if (!preview) {
    return null;
  }

  const allEntries = [...preview.changed, ...preview.added, ...preview.removed];
  return allEntries.find((entry) => entry.tool_name === toolName) ?? null;
}

export default function MetadataRefreshDiffCard({
  tool,
  preview,
  onPreview,
  onApply,
  isPreviewing = false,
  isApplying = false,
}: MetadataRefreshDiffCardProps) {
  const relevantDiff = findRelevantDiff(tool.tool_name, preview);
  const otherChangedTools = preview
    ? [...preview.changed, ...preview.added, ...preview.removed]
        .filter((entry) => entry.tool_name !== tool.tool_name)
        .map((entry) => entry.tool_name)
    : [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Re-fetch upstream metadata</CardTitle>
        <CardDescription>
          Fetch a fresh upstream snapshot, review the diff first, then decide whether to keep the published copy or adopt the upstream reference.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-secondary/20 p-4">
          <div>
            <p className="text-sm font-medium text-foreground">Latest upstream refresh</p>
            <p className="text-sm text-muted-foreground">
              {tool.metadata_last_fetched_at
                ? new Date(tool.metadata_last_fetched_at).toLocaleString()
                : 'No upstream refresh has been recorded for this tool yet.'}
            </p>
          </div>
          <Button type="button" variant="outline" disabled={isPreviewing || isApplying} onClick={() => void onPreview()}>
            <RefreshCw className={isPreviewing ? 'animate-spin' : ''} />
            {isPreviewing ? 'Previewing…' : 'Preview upstream diff'}
          </Button>
        </div>

        {preview?.warnings?.map((warning) => (
          <Alert key={warning}>
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle>Discovery warning</AlertTitle>
            <AlertDescription>{warning}</AlertDescription>
          </Alert>
        ))}

        {preview && !relevantDiff && preview.changed.length === 0 && preview.added.length === 0 && preview.removed.length === 0 && (
          <div className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
            No upstream metadata changes were detected for this tool.
          </div>
        )}

        {relevantDiff && (
          <div className="space-y-4 rounded-lg border border-border p-4">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-base font-semibold text-foreground">Diff review for {tool.tool_name}</h3>
              <Badge variant={relevantDiff.severity === 'warning' ? 'destructive' : 'secondary'}>
                {relevantDiff.schema_changed ? 'Schema warning' : relevantDiff.change_type}
              </Badge>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <div className="space-y-2 rounded-lg border border-border bg-secondary/20 p-4">
                <p className="text-sm font-medium text-foreground">Current published metadata</p>
                <p className="whitespace-pre-wrap text-sm text-muted-foreground">
                  {relevantDiff.effective_description || tool.description || 'No published description available.'}
                </p>
              </div>
              <div className="space-y-2 rounded-lg border border-border bg-secondary/20 p-4">
                <p className="text-sm font-medium text-foreground">Fresh upstream reference</p>
                <p className="whitespace-pre-wrap text-sm text-muted-foreground">
                  {relevantDiff.upstream_description || 'No upstream reference description returned.'}
                </p>
              </div>
            </div>

            {relevantDiff.schema_changed && (
              <Alert variant="destructive">
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle>Schema warning</AlertTitle>
                <AlertDescription>
                  Input schema changed upstream. Review execution compatibility before applying this refresh.
                </AlertDescription>
              </Alert>
            )}

            <div className="grid gap-3 md:grid-cols-2">
              <Button type="button" variant="outline" disabled={isApplying} onClick={() => void onApply('keep')}>
                {isApplying ? 'Applying…' : 'Keep current published metadata'}
              </Button>
              <Button type="button" disabled={isApplying} onClick={() => void onApply('adopt')}>
                {isApplying ? 'Applying…' : 'Adopt upstream reference'}
              </Button>
            </div>

            <div className="grid gap-3 text-xs text-muted-foreground md:grid-cols-2">
              <p>
                <span className="font-medium text-foreground">Keep</span> refreshes the upstream snapshot and execution schema while preserving the current published copy.
              </p>
              <p>
                <span className="font-medium text-foreground">Adopt</span> refreshes the snapshot and updates the published description to match the upstream reference.
              </p>
            </div>
          </div>
        )}

        {otherChangedTools.length > 0 && (
          <div className="rounded-lg border border-border bg-secondary/20 p-4 text-sm text-muted-foreground">
            Other same-server tool changes detected in this refresh: {otherChangedTools.join(', ')}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
