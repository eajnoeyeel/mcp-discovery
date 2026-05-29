import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import type { ParameterMetadataEntry } from '@/types/database';

export interface ReviewToolDraft {
  tool_name: string;
  description: string;
  upstream_description: string;
  input_schema: Record<string, unknown> | null;
  parameter_metadata: ParameterMetadataEntry[];
}

type EditableReviewToolField = 'tool_name' | 'upstream_description';

interface ReviewToolsStepProps {
  tools: ReviewToolDraft[];
  manualMode: boolean;
  warnings: string[];
  error: string;
  onToolChange: (index: number, field: EditableReviewToolField, value: string) => void;
  onAddTool: () => void;
  onRemoveTool: (index: number) => void;
  onBack: () => void;
  onContinue: () => void;
}

export default function ReviewToolsStep({
  tools,
  manualMode,
  warnings,
  error,
  onToolChange,
  onAddTool,
  onRemoveTool,
  onBack,
  onContinue,
}: ReviewToolsStepProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Review Tool Metadata</CardTitle>
        <CardDescription>
          Confirm the upstream tool set before you edit the provider-facing descriptions and guidance.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {manualMode && (
          <Alert>
            <AlertTitle>Manual tool entry</AlertTitle>
            <AlertDescription>
              Discovery did not return a usable tool list. Continue by entering the tools you want to publish now.
            </AlertDescription>
          </Alert>
        )}

        {warnings.length > 0 && (
          <Alert>
            <AlertTitle>Discovery warnings</AlertTitle>
            <AlertDescription>
              <ul className="list-disc space-y-1 pl-4">
                {warnings.map(warning => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}

        {tools.map((tool, index) => (
          <div key={`${tool.tool_name || 'tool'}-${index}`} className="rounded-lg border border-border p-4">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div>
                <h2 className="font-medium text-foreground">Tool {index + 1}</h2>
                {!manualMode && <p className="mt-1 text-sm text-muted-foreground">Fetched from the upstream MCP server.</p>}
              </div>
              {!manualMode && <Badge variant="secondary">Discovered</Badge>}
              {manualMode && tools.length > 1 && (
                <Button type="button" variant="ghost" onClick={() => onRemoveTool(index)}>
                  Remove
                </Button>
              )}
            </div>

            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor={`tool-name-${index}`}>Tool Name</Label>
                <Input
                  id={`tool-name-${index}`}
                  value={tool.tool_name}
                  onChange={event => onToolChange(index, 'tool_name', event.target.value)}
                  placeholder="lookup"
                  readOnly={!manualMode}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor={`tool-upstream-description-${index}`}>Upstream reference description</Label>
                <Textarea
                  id={`tool-upstream-description-${index}`}
                  value={tool.upstream_description}
                  onChange={event => onToolChange(index, 'upstream_description', event.target.value)}
                  placeholder="Describe the upstream tool as currently published by the provider."
                  readOnly={!manualMode}
                />
              </div>

              {tool.parameter_metadata.length > 0 ? (
                <div className="space-y-3">
                  <div className="space-y-1">
                    <Label>Structured parameter summary</Label>
                    <p className="text-sm text-muted-foreground">
                      Review required flags, types, and upstream descriptions before publishing overrides.
                    </p>
                  </div>
                  <div className="space-y-3">
                    {tool.parameter_metadata.map(parameter => (
                      <div
                        key={parameter.path}
                        className="rounded-lg border border-border/70 bg-secondary/30 p-3"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-mono text-sm text-foreground">{parameter.path}</span>
                          <Badge variant={parameter.required ? 'default' : 'outline'}>
                            {parameter.required ? 'Required' : 'Optional'}
                          </Badge>
                          {parameter.type && <Badge variant="secondary">{parameter.type}</Badge>}
                          {parameter.items_type && <Badge variant="outline">items: {parameter.items_type}</Badge>}
                          {parameter.enum_values.length > 0 && (
                            <Badge variant="outline">enum: {parameter.enum_values.join(', ')}</Badge>
                          )}
                        </div>
                        {parameter.description && (
                          <p className="mt-2 text-sm text-muted-foreground">{parameter.description}</p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <Alert>
                  <AlertTitle>Structured parameter metadata unavailable</AlertTitle>
                  <AlertDescription>
                    Discovery did not return a normalized parameter summary for this tool. Review the raw input schema
                    below before continuing.
                  </AlertDescription>
                </Alert>
              )}

              {tool.input_schema && (
                <div className="space-y-2">
                  <Label>{tool.parameter_metadata.length > 0 ? 'Raw schema reference' : 'Input schema fallback'}</Label>
                  <pre className="overflow-x-auto rounded-lg bg-secondary p-4 text-xs text-foreground">
                    {JSON.stringify(tool.input_schema, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          </div>
        ))}

        {manualMode && (
          <Button type="button" variant="outline" onClick={onAddTool}>
            Add Another Tool
          </Button>
        )}

        {error && (
          <Alert variant="destructive">
            <AlertTitle>Review step blocked</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <div className="flex flex-col gap-3 sm:flex-row sm:justify-between">
          <Button type="button" variant="outline" onClick={onBack}>
            Back to connection
          </Button>
          <Button type="button" onClick={onContinue}>
            Continue to Published Metadata
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
