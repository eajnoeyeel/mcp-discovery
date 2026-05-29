import { useEffect, useMemo, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { CopyButton } from '@/components/ui/copy-button';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import type { ProviderToolDetailResponse, UpdateProviderToolMetadataRequest } from '@/types/database';

interface MetadataEditorCardProps {
  tool: ProviderToolDetailResponse['tool'];
  onSave: (payload: UpdateProviderToolMetadataRequest) => Promise<unknown>;
  isSaving?: boolean;
}

function linesToText(lines?: string[] | null): string {
  return (lines ?? []).join('\n');
}

function parseLines(value: string): string[] {
  return value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
}

export default function MetadataEditorCard({ tool, onSave, isSaving = false }: MetadataEditorCardProps) {
  const [description, setDescription] = useState(tool.description ?? '');
  const [parameterNotes, setParameterNotes] = useState(tool.parameter_notes ?? '');
  const [usageExamples, setUsageExamples] = useState(linesToText(tool.usage_examples));
  const [usageHints, setUsageHints] = useState(linesToText(tool.usage_hints));
  const [justSaved, setJustSaved] = useState(false);

  useEffect(() => {
    setDescription(tool.description ?? '');
    setParameterNotes(tool.parameter_notes ?? '');
    setUsageExamples(linesToText(tool.usage_examples));
    setUsageHints(linesToText(tool.usage_hints));
  }, [tool.description, tool.parameter_notes, tool.tool_id, tool.usage_examples, tool.usage_hints]);

  const parsedExamples = useMemo(() => parseLines(usageExamples), [usageExamples]);
  const parsedHints = useMemo(() => parseLines(usageHints), [usageHints]);

  const isDirty =
    description !== (tool.description ?? '') ||
    parameterNotes !== (tool.parameter_notes ?? '') ||
    usageExamples !== linesToText(tool.usage_examples) ||
    usageHints !== linesToText(tool.usage_hints);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onSave({
      description,
      parameter_notes: parameterNotes,
      usage_examples: parsedExamples,
      usage_hints: parsedHints,
    });
    setJustSaved(true);
    setTimeout(() => setJustSaved(false), 3000);
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle>Edit published metadata</CardTitle>
          {tool.metadata_origin && <Badge variant="outline">{tool.metadata_origin}</Badge>}
        </div>
        <CardDescription>
          Keep the provider-managed public metadata separate from the upstream reference snapshot. Published metadata is what MLP exposes for tool selection.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="mb-4 flex flex-wrap gap-4 text-xs text-muted-foreground">
          <span>
            Last upstream fetch: {tool.metadata_last_fetched_at ? new Date(tool.metadata_last_fetched_at).toLocaleString() : 'Not fetched yet'}
          </span>
          <span>
            Last override edit: {tool.override_updated_at ? new Date(tool.override_updated_at).toLocaleString() : 'No override saved yet'}
          </span>
        </div>

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="rounded-lg border border-border p-4">
              <h3 className="text-base font-semibold text-foreground">Current published metadata</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                This editable copy is the provider-facing description, notes, and guidance clients see today.
              </p>

              <div className="mt-4 space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="published-description">Published description</Label>
                  <Textarea
                    id="published-description"
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    placeholder="Explain what this tool does, when it should win, and any constraints clients should know."
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="published-parameter-notes">Parameter notes</Label>
                  <Textarea
                    id="published-parameter-notes"
                    value={parameterNotes}
                    onChange={(event) => setParameterNotes(event.target.value)}
                    placeholder="Highlight the highest-signal parameters and any provider-specific caveats."
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="published-usage-examples">Usage examples</Label>
                  <Textarea
                    id="published-usage-examples"
                    value={usageExamples}
                    onChange={(event) => setUsageExamples(event.target.value)}
                    placeholder={['{"q": "docs"}', '{"q": "api"}'].join('\n')}
                  />
                  <p className="text-xs text-muted-foreground">Enter one example per line.</p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="published-usage-hints">Usage hints</Label>
                  <Textarea
                    id="published-usage-hints"
                    value={usageHints}
                    onChange={(event) => setUsageHints(event.target.value)}
                    placeholder={['Best for exact identifiers', 'Use for provider-owned documentation'].join('\n')}
                  />
                  <p className="text-xs text-muted-foreground">Enter one hint per line.</p>
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" disabled={!isDirty || isSaving}>
                {isSaving ? 'Saving…' : 'Save published metadata'}
              </Button>
              {justSaved && <span className="text-sm text-success">Saved</span>}
              <Button
                type="button"
                variant="outline"
                disabled={!isDirty || isSaving}
                onClick={() => {
                  setDescription(tool.description ?? '');
                  setParameterNotes(tool.parameter_notes ?? '');
                  setUsageExamples(linesToText(tool.usage_examples));
                  setUsageHints(linesToText(tool.usage_hints));
                }}
              >
                Reset edits
              </Button>
            </div>
          </form>

          <div className="rounded-lg border border-border bg-secondary/30 p-4">
            <h3 className="text-base font-semibold text-foreground">Upstream reference metadata</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              This read-only snapshot comes from the upstream MCP server and should stay separate from the published override.
            </p>

            <div className="mt-4 space-y-4">
              <div className="space-y-2">
                <Label>Upstream description</Label>
                <div className="rounded-md bg-background p-3 text-sm text-foreground">
                  {tool.upstream_description || 'No upstream reference description captured yet.'}
                </div>
              </div>

              <div className="space-y-2">
                <Label>Execution schema reference</Label>
                <div className="relative">
                  <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-background p-3 text-xs text-foreground">
                    {tool.input_schema ? JSON.stringify(tool.input_schema, null, 2) : 'No input schema available.'}
                  </pre>
                  {tool.input_schema && (
                    <CopyButton
                      text={JSON.stringify(tool.input_schema, null, 2)}
                      className="absolute right-2 top-2"
                    />
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
