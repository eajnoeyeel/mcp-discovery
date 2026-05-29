import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { ClipboardCopy } from 'lucide-react';
import type { ParameterMetadataEntry, PublishedParameterMetadataEntry } from '@/types/database';

export interface OverrideToolDraft {
  tool_name: string;
  description: string;
  upstream_description: string;
  input_schema: Record<string, unknown> | null;
  parameter_metadata: ParameterMetadataEntry[];
  published_parameter_metadata: PublishedParameterMetadataEntry[];
  parameter_notes: string;
  usage_examples: string[];
  usage_hints: string[];
}

type EditableOverrideToolField =
  | 'description'
  | 'parameter_notes'
  | 'usage_examples'
  | 'usage_hints';

interface EditOverridesStepProps {
  tools: OverrideToolDraft[];
  error: string;
  onToolFieldChange: (index: number, field: EditableOverrideToolField, value: string) => void;
  onPublishedParameterChange: (index: number, path: string, value: string) => void;
  onBack: () => void;
  onContinue: () => void;
}

function buildParameterFieldId(toolIndex: number, path: string): string {
  return `published-parameter-description-${toolIndex}-${path.replace(/[^a-zA-Z0-9]+/g, '-')}`;
}

function getPublishedDescription(
  publishedEntries: PublishedParameterMetadataEntry[],
  path: string,
): string {
  return publishedEntries.find(entry => entry.path === path)?.description ?? '';
}

export default function EditOverridesStep({
  tools,
  error,
  onToolFieldChange,
  onPublishedParameterChange,
  onBack,
  onContinue,
}: EditOverridesStepProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Edit Published Metadata</CardTitle>
        <CardDescription>
          This is the provider-managed copy MLP will publish. Keep the upstream metadata visible as reference while you
          refine the public description.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {tools.map((tool, index) => (
          <div key={`${tool.tool_name || 'tool'}-${index}`} className="rounded-lg border border-border p-4">
            <h2 className="font-medium text-foreground">{tool.tool_name || `Tool ${index + 1}`}</h2>
            {tool.upstream_description && (
              <div className="mt-4 space-y-2 rounded-lg bg-secondary/50 p-4">
                <div className="flex items-center justify-between">
                  <Label>Upstream reference</Label>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 gap-1.5 text-xs"
                    onClick={() => onToolFieldChange(index, 'description', tool.upstream_description)}
                  >
                    <ClipboardCopy className="h-3 w-3" />
                    Use as published description
                  </Button>
                </div>
                <p className="text-sm text-muted-foreground whitespace-pre-wrap">{tool.upstream_description}</p>
              </div>
            )}

            <div className="mt-4 space-y-4">
              <div className="space-y-2">
                <Label htmlFor={`published-description-${index}`}>Published description</Label>
                <Textarea
                  id={`published-description-${index}`}
                  value={tool.description}
                  onChange={event => onToolFieldChange(index, 'description', event.target.value)}
                  placeholder="Explain what this tool does, when it should be selected, and how it differs from alternatives."
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor={`parameter-notes-${index}`}>Parameter notes</Label>
                <Textarea
                  id={`parameter-notes-${index}`}
                  value={tool.parameter_notes}
                  onChange={event => onToolFieldChange(index, 'parameter_notes', event.target.value)}
                  placeholder="Highlight the highest-signal parameters and any provider-specific caveats."
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor={`usage-examples-${index}`}>Usage examples</Label>
                <Textarea
                  id={`usage-examples-${index}`}
                  value={tool.usage_examples.join('\n')}
                  onChange={event => onToolFieldChange(index, 'usage_examples', event.target.value)}
                  placeholder={['{"q": "docs"}', '{"q": "api"}'].join('\n')}
                />
                <p className="text-xs text-muted-foreground">Enter one example per line.</p>
              </div>

              <div className="space-y-2">
                <Label htmlFor={`usage-hints-${index}`}>Usage hints</Label>
                <Textarea
                  id={`usage-hints-${index}`}
                  value={tool.usage_hints.join('\n')}
                  onChange={event => onToolFieldChange(index, 'usage_hints', event.target.value)}
                  placeholder={['Best for exact identifiers', 'Use for provider-owned documentation'].join('\n')}
                />
                <p className="text-xs text-muted-foreground">Enter one hint per line.</p>
              </div>

              {tool.parameter_metadata.length > 0 ? (
                <div className="space-y-3 rounded-lg border border-dashed border-border p-4">
                  <div className="space-y-1">
                    <Label>Published parameter descriptions</Label>
                    <p className="text-sm text-muted-foreground">
                      Parameter paths and types stay locked to upstream discovery. Edit only the published descriptions.
                    </p>
                  </div>
                  <div className="space-y-4">
                    {tool.parameter_metadata.map(parameter => (
                      <div key={parameter.path} className="space-y-2 rounded-lg bg-secondary/30 p-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-mono text-sm text-foreground">{parameter.path}</span>
                          <Badge variant={parameter.required ? 'default' : 'outline'}>
                            {parameter.required ? 'Required' : 'Optional'}
                          </Badge>
                          {parameter.type && <Badge variant="secondary">{parameter.type}</Badge>}
                        </div>
                        {parameter.description && (
                          <p className="text-sm text-muted-foreground">
                            Upstream description: {parameter.description}
                          </p>
                        )}
                        <div className="space-y-2">
                          <Label htmlFor={buildParameterFieldId(index, parameter.path)}>
                            Published description for {parameter.path}
                          </Label>
                          <Textarea
                            id={buildParameterFieldId(index, parameter.path)}
                            value={getPublishedDescription(tool.published_parameter_metadata, parameter.path)}
                            onChange={event =>
                              onPublishedParameterChange(index, parameter.path, event.target.value)
                            }
                            placeholder="Describe how LLM clients should interpret and supply this parameter."
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <Alert>
                  <AlertTitle>No structured parameter metadata</AlertTitle>
                  <AlertDescription>
                    Discovery did not return structured parameters for this tool, so this step only captures tool-level
                    metadata overrides.
                  </AlertDescription>
                </Alert>
              )}
            </div>
          </div>
        ))}

        {error && (
          <Alert variant="destructive">
            <AlertTitle>Metadata step blocked</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <div className="flex flex-col gap-3 sm:flex-row sm:justify-between">
          <Button type="button" variant="outline" onClick={onBack}>
            Back to review
          </Button>
          <Button type="button" onClick={onContinue}>
            Continue to Confirmation
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
