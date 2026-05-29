import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import type { ClientAuthConfig, ParameterMetadataEntry, PublishedParameterMetadataEntry } from '@/types/database';

interface ConfirmServerSummary {
  serverId: string;
  name: string;
  url: string;
  description: string;
  tags: string[];
  clientAuth?: ClientAuthConfig;
}

interface ConfirmToolSummary {
  render_key: string;
  tool_name: string;
  description: string;
  upstream_description: string;
  parameter_metadata: ParameterMetadataEntry[];
  published_parameter_metadata: PublishedParameterMetadataEntry[];
  parameter_notes: string;
  usage_examples: string[];
  usage_hints: string[];
}

interface ConfirmRegistrationStepProps {
  server: ConfirmServerSummary;
  tools: ConfirmToolSummary[];
  error: string;
  isSubmitting: boolean;
  onBack: () => void;
  onSubmit: () => void;
}

export default function ConfirmRegistrationStep({
  server,
  tools,
  error,
  isSubmitting,
  onBack,
  onSubmit,
}: ConfirmRegistrationStepProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Confirm Registration</CardTitle>
        <CardDescription>
          Review the final payload before the provider registration request is submitted.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <section className="rounded-lg border border-border p-4">
          <h2 className="font-medium text-foreground">Server summary</h2>
          <dl className="mt-4 grid gap-4 sm:grid-cols-2">
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">Server ID</dt>
              <dd className="mt-1 text-sm text-foreground">{server.serverId}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">Server name</dt>
              <dd className="mt-1 text-sm text-foreground">{server.name}</dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">Server URL</dt>
              <dd className="mt-1 text-sm text-foreground">{server.url}</dd>
            </div>
            {server.description && (
              <div className="sm:col-span-2">
                <dt className="text-xs uppercase tracking-wide text-muted-foreground">Server description</dt>
                <dd className="mt-1 whitespace-pre-wrap text-sm text-foreground">{server.description}</dd>
              </div>
            )}
            {server.tags.length > 0 && (
              <div className="sm:col-span-2">
                <dt className="text-xs uppercase tracking-wide text-muted-foreground">Tags</dt>
                <dd className="mt-2 flex flex-wrap gap-2">
                  {server.tags.map(tag => (
                    <Badge key={tag} variant="secondary">
                      {tag}
                    </Badge>
                  ))}
                </dd>
              </div>
            )}
            {server.clientAuth && (
              <div className="sm:col-span-2">
                <dt className="text-xs uppercase tracking-wide text-muted-foreground">Delegated client auth</dt>
                <dd className="mt-2 space-y-2 text-sm text-foreground">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="secondary">{server.clientAuth.provider_key}</Badge>
                    <Badge variant="outline">
                      {server.clientAuth.scope_mode === 'override' ? 'Override scopes' : 'Default scopes'}
                    </Badge>
                  </div>
                  <p>
                    {server.clientAuth.required_scopes.length > 0
                      ? server.clientAuth.required_scopes.join(', ')
                      : 'Uses the provider defaults only.'}
                  </p>
                </dd>
              </div>
            )}
          </dl>
        </section>

        <section className="space-y-4">
          <h2 className="font-medium text-foreground">Tool payload preview</h2>
          {tools.map(tool => (
            <div key={tool.render_key} className="rounded-lg border border-border p-4">
              <div className="flex items-start justify-between gap-3">
                <h3 className="font-medium text-foreground">{tool.tool_name}</h3>
                <Badge variant="outline">Ready</Badge>
              </div>
              <dl className="mt-4 space-y-3 text-sm">
                <div>
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">Published description</dt>
                  <dd className="mt-1 whitespace-pre-wrap text-foreground">{tool.description || '—'}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">Upstream reference</dt>
                  <dd className="mt-1 whitespace-pre-wrap text-muted-foreground">{tool.upstream_description || '—'}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">Parameter notes</dt>
                  <dd className="mt-1 whitespace-pre-wrap text-foreground">{tool.parameter_notes || '—'}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">Parameter descriptions</dt>
                  <dd className="mt-2 space-y-2 text-foreground">
                    {tool.published_parameter_metadata.length > 0 ? (
                      tool.published_parameter_metadata.map(entry => {
                        const upstreamParameter = tool.parameter_metadata.find(
                          parameter => parameter.path === entry.path,
                        );

                        return (
                          <div key={entry.path} className="rounded-lg bg-secondary/40 p-3">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-mono text-xs text-foreground">{entry.path}</span>
                              {upstreamParameter?.type && (
                                <Badge variant="secondary">{upstreamParameter.type}</Badge>
                              )}
                              <Badge variant={upstreamParameter?.required ? 'default' : 'outline'}>
                                {upstreamParameter?.required ? 'Required' : 'Optional'}
                              </Badge>
                            </div>
                            <p className="mt-2 whitespace-pre-wrap text-sm text-foreground">
                              {entry.description || '—'}
                            </p>
                          </div>
                        );
                      })
                    ) : tool.parameter_metadata.length > 0 ? (
                      'No published parameter descriptions provided.'
                    ) : (
                      'Structured parameter metadata unavailable from discovery.'
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">Usage examples</dt>
                  <dd className="mt-1 whitespace-pre-wrap text-foreground">
                    {tool.usage_examples.length > 0 ? tool.usage_examples.join('\n') : '—'}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">Usage hints</dt>
                  <dd className="mt-1 whitespace-pre-wrap text-foreground">
                    {tool.usage_hints.length > 0 ? tool.usage_hints.join('\n') : '—'}
                  </dd>
                </div>
              </dl>
            </div>
          ))}
        </section>

        {error && (
          <Alert variant="destructive">
            <AlertTitle>Registration failed</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <div className="flex flex-col gap-3 sm:flex-row sm:justify-between">
          <Button type="button" variant="outline" onClick={onBack}>
            Back to metadata
          </Button>
          <Button type="button" onClick={onSubmit} disabled={isSubmitting}>
            {isSubmitting ? 'Registering…' : 'Register Server'}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
